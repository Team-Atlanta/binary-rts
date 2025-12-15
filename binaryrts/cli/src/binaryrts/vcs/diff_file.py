"""
Module for parsing unified diff files and providing file content without git.

This allows BinaryRTS to work with standalone diff files instead of requiring
git revisions, useful for CI/CD environments where only a diff is available.
"""
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Pattern

from binaryrts.vcs.base import ChangelistItem, ChangelistItemAction, Changelist


class DiffFileClient:
    """
    Client for parsing unified diff files and providing file contents.

    This class mimics the interface of GitClient but works with a diff file
    instead of git revisions. It can work with repositories in either state:
    - repo_state="new": Repository contains post-change files (reverse-apply diff for old)
    - repo_state="old": Repository contains pre-change files (forward-apply diff for new)
    """

    diff_pattern: Pattern = re.compile(r"^diff --git a/(?P<filepath>.*) b/.*$")
    hunk_pattern: Pattern = re.compile(
        r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
    )

    def __init__(
        self,
        root: Path,
        diff_file: Optional[Path] = None,
        repo_state: str = "new",
        diff_content: Optional[str] = None,
    ) -> None:
        """
        Initialize the DiffFileClient.

        Args:
            root: Repository root directory
            diff_file: Path to the unified diff file (optional if diff_content provided)
            repo_state: Either "new" (repo has changes applied) or "old" (repo has original files)
            diff_content: Direct diff content string (optional, alternative to diff_file)
        """
        if diff_file is None and diff_content is None:
            raise ValueError("Either diff_file or diff_content must be provided")
        self.root = root
        self.diff_file = diff_file
        self.repo_state = repo_state  # "new" or "old"
        self._diff_content: Optional[str] = diff_content
        self._changelist: Optional[Changelist] = None
        self._file_diffs: Dict[str, str] = {}  # filepath -> diff section for that file

    @property
    def diff_content(self) -> str:
        """Lazily load and cache the diff file content."""
        if self._diff_content is None:
            if self.diff_file is None:
                raise ValueError("No diff file or content available")
            self._diff_content = self.diff_file.read_text(encoding="utf-8", errors="replace")
        return self._diff_content

    def get_diff(
        self,
        from_revision: str = "",
        to_revision: str = "",
    ) -> Changelist:
        """
        Parse the diff file and return a Changelist.

        The from_revision and to_revision parameters are ignored when using
        a diff file - they're kept for API compatibility with GitClient.
        """
        if self._changelist is not None:
            return self._changelist

        items: Set[ChangelistItem] = set()
        lines = self.diff_content.splitlines()
        current_file: Optional[str] = None
        current_diff_lines: List[str] = []

        for idx, line in enumerate(lines):
            # Check for new file diff header
            if line.startswith("diff --git"):
                # Save previous file's diff
                if current_file is not None:
                    self._file_diffs[current_file] = "\n".join(current_diff_lines)

                match = re.search(self.diff_pattern, line)
                if match:
                    current_file = match.group("filepath")
                    current_diff_lines = [line]

                    # Determine action from subsequent lines
                    action = ChangelistItemAction.MODIFIED
                    if idx + 1 < len(lines):
                        next_line = lines[idx + 1]
                        if "new file mode" in next_line:
                            action = ChangelistItemAction.ADDED
                        elif "deleted file mode" in next_line:
                            action = ChangelistItemAction.DELETED

                    items.add(ChangelistItem(filepath=Path(current_file), action=action))
            elif current_file is not None:
                current_diff_lines.append(line)

        # Save last file's diff
        if current_file is not None:
            self._file_diffs[current_file] = "\n".join(current_diff_lines)

        self._changelist = Changelist(items=list(items))
        logging.debug(
            "Diff file has changelist with %d items:\n%s"
            % (
                len(self._changelist.items),
                "\n".join(
                    map(lambda i: f"{i.action.value} {i.filepath}", self._changelist.items)
                ),
            )
        )
        return self._changelist

    def get_file_content_at_revision(self, revision: str, filepath: Path) -> str:
        """
        Get file content at a specific "revision".

        The behavior depends on repo_state:
        - repo_state="new": repo has post-change files
          - "new"/"HEAD"/"to" revision: return current file from disk
          - "old"/"from" revision: reverse-apply diff to get old content
        - repo_state="old": repo has pre-change files
          - "old"/"from" revision: return current file from disk
          - "new"/"HEAD"/"to" revision: forward-apply diff to get new content

        Args:
            revision: Revision identifier (used to determine old vs new)
            filepath: Path to the file (relative to repo root)
        """
        # Normalize filepath
        if filepath.is_absolute():
            filepath = filepath.relative_to(self.root)
        filepath_str = str(filepath).replace("\\", "/")

        # Determine if we want old or new content
        is_new_revision = revision.lower() in ("head", "new", "to", "")

        if self.repo_state == "new":
            # Repo has new (post-change) files
            if is_new_revision:
                # Return current file content from disk
                return self._read_file_from_disk(filepath)
            else:
                # Return old content by reverse-applying the diff
                return self._get_old_file_content(filepath_str)
        else:
            # repo_state == "old": Repo has old (pre-change) files
            if is_new_revision:
                # Return new content by forward-applying the diff
                return self._get_new_file_content(filepath_str)
            else:
                # Return current file content from disk
                return self._read_file_from_disk(filepath)

    def _read_file_from_disk(self, filepath: Path) -> str:
        """Read file content from disk."""
        full_path = self.root / filepath
        if full_path.exists():
            return full_path.read_text(encoding="utf-8", errors="replace")
        else:
            # File might have been deleted - return empty
            return ""

    def _get_new_file_content(self, filepath: str) -> str:
        """
        Get the new (post-change) content of a file by forward-applying the diff.

        For modified files: takes current content and applies the diff changes
        For added files: reconstructs content from diff (all lines are additions)
        For deleted files: returns empty string (file will be deleted)
        """
        # Make sure changelist is parsed
        self.get_diff()

        # Find the change item for this file
        item: Optional[ChangelistItem] = None
        for ci in self._changelist.items:
            if str(ci.filepath).replace("\\", "/") == filepath:
                item = ci
                break

        if item is None:
            # File not in diff - return current content
            return self._read_file_from_disk(Path(filepath))

        if item.action == ChangelistItemAction.DELETED:
            # File will be deleted - return empty
            return ""

        if item.action == ChangelistItemAction.ADDED:
            # File was added - reconstruct from diff (all lines are +)
            return self._reconstruct_added_file(filepath)

        # MODIFIED: forward-apply the diff to current content
        current_content = self._read_file_from_disk(Path(filepath))
        if not current_content:
            logging.warning(f"Modified file {filepath} not found on disk")
            return ""

        return self._forward_apply_diff(filepath, current_content)

    def _reconstruct_added_file(self, filepath: str) -> str:
        """Reconstruct an added file's content from the diff (all + lines)."""
        if filepath not in self._file_diffs:
            return ""

        diff_section = self._file_diffs[filepath]
        lines = []
        in_hunk = False

        for line in diff_section.splitlines():
            if line.startswith("@@"):
                in_hunk = True
                continue
            if in_hunk:
                if line.startswith("+"):
                    # This is a line in the new file
                    lines.append(line[1:])  # Remove the + prefix
                elif line.startswith("-"):
                    # Removed line - skip for new content
                    continue
                elif line.startswith(" "):
                    # Context line
                    lines.append(line[1:])
                elif line.startswith("\\"):
                    # "\ No newline at end of file" - skip
                    continue

        return "\n".join(lines)

    def _forward_apply_diff(self, filepath: str, current_content: str) -> str:
        """
        Forward-apply a diff to get the new file content.

        This takes the current (old) content and applies the changes described
        in the diff to produce the new content.
        """
        if filepath not in self._file_diffs:
            return current_content

        diff_section = self._file_diffs[filepath]
        current_lines = current_content.splitlines()

        # Parse all hunks and their changes
        hunks = self._parse_hunks(diff_section)

        # Apply hunks in reverse order (from bottom to top of file)
        # to avoid line number shifting issues
        for hunk in reversed(hunks):
            current_lines = self._forward_apply_hunk(current_lines, hunk)

        return "\n".join(current_lines)

    def _forward_apply_hunk(self, lines: List[str], hunk: dict) -> List[str]:
        """
        Forward-apply a single hunk to the file lines.

        To forward-apply a hunk:
        - Lines starting with - become deletions (remove them)
        - Lines starting with + become additions (add them)
        - Context lines stay the same
        """
        # old_start is 1-indexed, convert to 0-indexed
        old_start_idx = hunk["old_start"] - 1

        # Build the new content for this section
        new_section = []
        for hunk_line in hunk["lines"]:
            if hunk_line.startswith("+"):
                # This is added in new, include it
                new_section.append(hunk_line[1:])
            elif hunk_line.startswith("-"):
                # This was in old, skip it
                continue
            elif hunk_line.startswith(" "):
                # Context line
                new_section.append(hunk_line[1:])
            elif hunk_line.startswith("\\"):
                # No newline marker - skip
                continue

        # Replace the old section with the new section
        # The old section spans from old_start to old_start + old_count
        old_end_idx = old_start_idx + hunk["old_count"]

        result = lines[:old_start_idx] + new_section + lines[old_end_idx:]
        return result

    def _get_old_file_content(self, filepath: str) -> str:
        """
        Get the old (pre-change) content of a file by reverse-applying the diff.

        For modified files: takes current content and undoes the diff changes
        For added files: returns empty string (file didn't exist)
        For deleted files: reconstructs content from diff (all lines are removals)
        """
        # Make sure changelist is parsed
        self.get_diff()

        # Find the change item for this file
        item: Optional[ChangelistItem] = None
        for ci in self._changelist.items:
            if str(ci.filepath).replace("\\", "/") == filepath:
                item = ci
                break

        if item is None:
            # File not in diff - return current content
            full_path = self.root / filepath
            if full_path.exists():
                return full_path.read_text(encoding="utf-8", errors="replace")
            return ""

        if item.action == ChangelistItemAction.ADDED:
            # File was added - didn't exist before
            return ""

        if item.action == ChangelistItemAction.DELETED:
            # File was deleted - reconstruct from diff (all lines are -)
            return self._reconstruct_deleted_file(filepath)

        # MODIFIED: reverse-apply the diff to current content
        full_path = self.root / filepath
        if not full_path.exists():
            logging.warning(f"Modified file {filepath} not found on disk")
            return ""

        current_content = full_path.read_text(encoding="utf-8", errors="replace")
        return self._reverse_apply_diff(filepath, current_content)

    def _reconstruct_deleted_file(self, filepath: str) -> str:
        """Reconstruct a deleted file's content from the diff (all - lines)."""
        if filepath not in self._file_diffs:
            return ""

        diff_section = self._file_diffs[filepath]
        lines = []
        in_hunk = False

        for line in diff_section.splitlines():
            if line.startswith("@@"):
                in_hunk = True
                continue
            if in_hunk:
                if line.startswith("-"):
                    # This was a line in the old file
                    lines.append(line[1:])  # Remove the - prefix
                elif line.startswith("+"):
                    # Added line - skip for old content
                    continue
                elif line.startswith(" "):
                    # Context line
                    lines.append(line[1:])
                elif line.startswith("\\"):
                    # "\ No newline at end of file" - skip
                    continue

        return "\n".join(lines)

    def _reverse_apply_diff(self, filepath: str, current_content: str) -> str:
        """
        Reverse-apply a diff to get the old file content.

        This takes the current (new) content and undoes the changes described
        in the diff to produce the old content.
        """
        if filepath not in self._file_diffs:
            return current_content

        diff_section = self._file_diffs[filepath]
        current_lines = current_content.splitlines()

        # Parse all hunks and their changes
        hunks = self._parse_hunks(diff_section)

        # Apply hunks in reverse order (from bottom to top of file)
        # to avoid line number shifting issues
        for hunk in reversed(hunks):
            current_lines = self._reverse_apply_hunk(current_lines, hunk)

        return "\n".join(current_lines)

    def _parse_hunks(self, diff_section: str) -> List[dict]:
        """Parse all hunks from a diff section."""
        hunks = []
        current_hunk = None

        for line in diff_section.splitlines():
            match = re.match(self.hunk_pattern, line)
            if match:
                if current_hunk is not None:
                    hunks.append(current_hunk)
                current_hunk = {
                    "old_start": int(match.group("old_start")),
                    "old_count": int(match.group("old_count") or 1),
                    "new_start": int(match.group("new_start")),
                    "new_count": int(match.group("new_count") or 1),
                    "lines": [],
                }
            elif current_hunk is not None:
                if line.startswith(("+", "-", " ", "\\")):
                    current_hunk["lines"].append(line)

        if current_hunk is not None:
            hunks.append(current_hunk)

        return hunks

    def _reverse_apply_hunk(self, lines: List[str], hunk: dict) -> List[str]:
        """
        Reverse-apply a single hunk to the file lines.

        To reverse a hunk:
        - Lines starting with + become deletions (remove them)
        - Lines starting with - become additions (add them back)
        - Context lines stay the same
        """
        # new_start is 1-indexed, convert to 0-indexed
        new_start_idx = hunk["new_start"] - 1

        # Build the old content for this section
        old_section = []
        for hunk_line in hunk["lines"]:
            if hunk_line.startswith("-"):
                # This was in old, add it back
                old_section.append(hunk_line[1:])
            elif hunk_line.startswith("+"):
                # This was added in new, skip it
                continue
            elif hunk_line.startswith(" "):
                # Context line
                old_section.append(hunk_line[1:])
            elif hunk_line.startswith("\\"):
                # No newline marker - skip
                continue

        # Replace the new section with the old section
        # The new section spans from new_start to new_start + new_count
        new_end_idx = new_start_idx + hunk["new_count"]

        result = lines[:new_start_idx] + old_section + lines[new_end_idx:]
        return result
