import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

import typer

from binaryrts.parser.coverage import (
    FunctionLookupTable,
    TestFunctionTraces,
    TestFileTraces,
    TEST_LOOKUP_FILE,
)
from binaryrts.rts.base import RTSAlgo, SelectionCause
from binaryrts.rts.cpp import (
    CppFunctionLevelRTS,
    CppFileLevelRTS,
)
from binaryrts.rts.syscall import SyscallFileLevelRTS
from binaryrts.util.fs import has_ext
from binaryrts.util.logging import LogEvent
from binaryrts.vcs.git import is_git_repo, GitClient
from binaryrts.vcs.diff_file import DiffFileClient
from binaryrts.commands.utils import format_test_list


def get_dirty_diff(repo_root: Path) -> str:
    """Get uncommitted changes (staged + unstaged) as a unified diff."""
    result = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git diff HEAD failed: {result.stderr}")
    return result.stdout

app = typer.Typer()

INCLUDED_TESTS_FILE: str = "included.txt"
EXCLUDED_TESTS_FILE: str = "excluded.txt"
SELECTION_CAUSES_FILE: str = "selection-causes.txt"
EVENT_LOG: str = "event.log"
RTS_START_EVENT: str = "START_BINARY_RTS_SELECTION"
RTS_END_EVENT: str = "END_BINARY_RTS_SELECTION"


@dataclass
class SelectCommonOptions:
    vcs_client: Union[GitClient, DiffFileClient]
    output: Path
    from_revision: str
    to_revision: str
    includes_regex: str
    excludes_regex: str
    repo_root: Path
    simple_output: bool = False


@dataclass
class RTSConfiguration:
    name: str
    file_level: bool
    scope_analysis: bool
    overload_analysis: bool
    virtual_analysis: bool
    non_functional_analysis: bool
    non_functional_retest_all: bool
    non_functional_analysis_depth: int = field(default=1)


def _repo_callback(ctx: typer.Context, param: typer.CallbackParam, value: Path) -> Path:
    # Skip git validation if --diff-file is provided
    # We check this by looking at the raw CLI params since ctx.params may not have all values yet
    return value


@app.callback()
def select(
    ctx: typer.Context,
    from_revision: str = typer.Option("", "--from", "-f", help="Git revision to diff from (ignored if --diff-file or --dirty is used)"),
    to_revision: str = typer.Option("", "--to", "-t", help="Git revision to diff to (ignored if --diff-file or --dirty is used)"),
    repo_root: Path = typer.Option(
        lambda: Path(os.getcwd()),
        "--repo",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        callback=_repo_callback,
    ),
    diff_file: Optional[Path] = typer.Option(
        None,
        "--diff-file",
        "--diff",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        help="Path to a unified diff file. When provided, --from and --to are ignored.",
    ),
    dirty: bool = typer.Option(
        False,
        "--dirty",
        "--uncommitted",
        help="Use uncommitted changes (staged + unstaged) as the diff. Repo must be a git directory.",
    ),
    repo_state: str = typer.Option(
        "old",
        "--repo-state",
        help="State of repository when using --diff-file: 'old' (pre-change, default) or 'new' (post-change).",
    ),
    output: Path = typer.Option(
        lambda: Path(os.getcwd()),
        "-o",
        writable=True,
        exists=False,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    includes_regex: str = typer.Option(
        ".*",
        "--includes",
        help="Regular expression to include certain files or directories from selection.",
    ),
    excludes_regex: str = typer.Option(
        "",
        "--excludes",
        help="Regular expression to exclude certain files or directories from selection.",
    ),
    simple_output: bool = typer.Option(
        False,
        "--simple-output",
        "--simple",
        help="Output simple test names (strips *!!!...!!!* markers) with trailing newlines for easier shell parsing.",
    ),
):
    """
    Select tests based on code changes.

    Changes can be specified via:
    - Git revisions (--from/--to): Compare two commits
    - Diff file (--diff-file): Use a unified diff file
    - Dirty mode (--dirty): Use uncommitted changes in the working directory
    """
    vcs_client: Union[GitClient, DiffFileClient]

    if dirty:
        # Use dirty/uncommitted changes mode
        if not is_git_repo(path=repo_root):
            raise typer.BadParameter(
                "Repository root must be a git directory when using --dirty."
            )
        diff_content = get_dirty_diff(repo_root)
        if not diff_content.strip():
            logging.warning("No uncommitted changes found (git diff HEAD is empty)")
        logging.info(f"Using dirty/uncommitted changes (repo_state=new)")
        # Working directory has changes applied, so repo_state is always "new"
        vcs_client = DiffFileClient(root=repo_root, diff_content=diff_content, repo_state="new")
        from_revision = "HEAD"
        to_revision = "dirty"
    elif diff_file is not None:
        # Use diff file mode - no git required
        logging.info(f"Using diff file: {diff_file} (repo_state={repo_state})")
        vcs_client = DiffFileClient(root=repo_root, diff_file=diff_file, repo_state=repo_state)
        # Set meaningful revision names for diff file mode
        from_revision = "old"
        to_revision = "new"
    else:
        # Use git mode - validate repo and set defaults
        if not is_git_repo(path=repo_root):
            raise typer.BadParameter(
                "Repository root must be a git directory when not using --diff-file or --dirty. "
                "Use --diff-file to provide a unified diff instead."
            )
        if not from_revision:
            from_revision = "main"
        if not to_revision:
            to_revision = "HEAD"
        vcs_client = GitClient(root=repo_root)

    ctx.obj = SelectCommonOptions(
        vcs_client=vcs_client,
        output=output,
        from_revision=from_revision,
        to_revision=to_revision,
        includes_regex=includes_regex,
        excludes_regex=excludes_regex,
        repo_root=repo_root,
        simple_output=simple_output,
    )
    output.mkdir(parents=True, exist_ok=True)


@app.command()
def cpp(
    ctx: typer.Context,
    function_lookup_file: Path = typer.Option(
        ...,
        "--lookup",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
    ),
    test_function_traces_file: Path = typer.Option(
        ...,
        "--traces",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
    ),
    non_functional_analysis: bool = typer.Option(
        False,
        "--non-functional",
        help="Enables call analysis of non-functional entities (macros, globals, member variables).",
    ),
    non_functional_analysis_depth: int = typer.Option(
        2,  # we pick 2, as it is common practice to split C/C++ projects into `inc` and `src` subdirectories
        "--non-functional-depth",
        help="Configures non-functional analysis depth, "
        "i.e., how far up to walk the filesystem tree to find usage of non-functional entities.",
    ),
    non_functional_retest_all: bool = typer.Option(
        False,
        "--non-functional-retest-all",
        help="Fall back to retest-all in case any changes to non-functional entities are present.",
    ),
    file_level: bool = typer.Option(
        False,
        "--file-level",
        help="Enables file-level rather than the default function-level selection granularity.",
    ),
    scope_analysis: bool = typer.Option(
        False,
        "--scope-overrides",
        "--scope-analysis",
        "--scope",
        help="Enables analysis to mark functions as affected that have a similar signature as an added function. "
        "This anticipates that if a function is added, it could always override/replace a function from an outer scope.",
    ),
    overload_analysis: bool = typer.Option(
        False,
        "--overload-analysis",
        "--overload",
        help="Enables analysis to mark functions as affected that have a similar name as an added function. "
        "This anticipates that if a function is added, it could always overload existing functions.",
    ),
    virtual_analysis: bool = typer.Option(
        False,
        "--virtual-analysis",
        "--virtual",
        help="Enables analysis to mark member functions as affected that have a similar signature."
        "This anticipates that if a virtual member function is overridden, "
        "tests using the base implementation need to be retested.",
    ),
    generated_code_regex: Optional[str] = typer.Option(
        None,
        "--generated-code",
        help="A regex to directories where generated code is located.",
    ),
    generated_code_exts: Optional[List[str]] = typer.Option(
        [],
        "--generated-ext",
        help="A list of file extensions that trigger all functions from files within "
        "the generated code directories to be affected.",
    ),
    retest_all_regex: Optional[str] = typer.Option(
        None,
        "--retest-all",
        help="A regex for changed files that should trigger a retest-all.",
    ),
    file_level_regex: Optional[str] = typer.Option(
        None,
        "--file-level-regex",
        help="A regex for changed files that should trigger a file-level selection for non-functional changes. "
        "Effectively, if non-functional changes to matching files occur, "
        "all functions inside these files will be marked as affected.",
    ),
    use_cscope: bool = typer.Option(
        False,
        "--cscope",
        help="Whether to use cscope for non-functional analysis or naive text-based lookup."
        "More efficient lookup using grep [Linux] or findstr [Windows] are experimental "
        "and need to be manually enabled in the source code.",
    ),
    evaluation: bool = typer.Option(
        False,
        "--evaluation",
        help="Performs test selection in evaluation mode, meaning that all combinations of parameters are run.",
    ),
    java: bool = typer.Option(
        False,
        "--java",
        help="Will use `java` prefix instead of `cpp` for output directories when using `--evaluation`. "
        "Has no effect without `--evaluation`.",
    ),
):
    """
    Select C++ tests for GoogleTesting framework.
    """
    opts: SelectCommonOptions = ctx.obj

    logging.info(f"Loading function table from {function_lookup_file}")
    function_lookup_table: FunctionLookupTable
    if has_ext(function_lookup_file, exts=[".csv"]):
        function_lookup_table = FunctionLookupTable.from_csv(
            function_lookup_file, root_dir=opts.repo_root
        )
    elif has_ext(function_lookup_file, exts=[".pkl"]):
        function_lookup_table = FunctionLookupTable.from_pickle(function_lookup_file)
        function_lookup_table.root_dir = opts.repo_root
    else:
        raise Exception(
            f"Provided invalid function lookup file format, only .csv and .pkl are currently supported."
        )

    logging.info(f"Loading test function traces from {test_function_traces_file}")
    test_function_traces: TestFunctionTraces
    if has_ext(test_function_traces_file, exts=[".csv"]):
        test_function_traces = TestFunctionTraces.from_csv(
            test_function_traces_file,
            (test_function_traces_file.parent / TEST_LOOKUP_FILE)
            if (test_function_traces_file.parent / TEST_LOOKUP_FILE).exists()
            else None,
        )
    elif has_ext(test_function_traces_file, exts=[".pkl"]):
        test_function_traces = TestFunctionTraces.from_pickle(test_function_traces_file)
    else:
        raise Exception(
            f"Provided invalid test traces file format, only .csv and .pkl are currently supported."
        )

    def _run_rts(config: RTSConfiguration):
        rts_algo: RTSAlgo
        output_dir: Path = opts.output / config.name
        output_dir.mkdir(parents=True, exist_ok=True)

        LogEvent(name=f"{RTS_START_EVENT}_{config.name or 'default'}").append(
            log_file=output_dir / EVENT_LOG
        )
        try:
            if config.file_level:
                rts_algo = CppFileLevelRTS(
                    vcs_client=opts.vcs_client,
                    function_lookup_table=function_lookup_table,
                    test_function_traces=test_function_traces,
                    output_dir=output_dir,
                    includes_regex=opts.includes_regex,
                    excludes_regex=opts.excludes_regex,
                    generated_code_regex=generated_code_regex,
                    generated_code_exts=generated_code_exts,
                    retest_all_regex=retest_all_regex,
                )
            else:
                rts_algo = CppFunctionLevelRTS(
                    vcs_client=opts.vcs_client,
                    function_lookup_table=function_lookup_table,
                    test_function_traces=test_function_traces,
                    output_dir=output_dir,
                    non_functional_analysis=config.non_functional_analysis,
                    non_functional_analysis_depth=config.non_functional_analysis_depth,
                    non_functional_retest_all=config.non_functional_retest_all,
                    virtual_analysis=config.virtual_analysis,
                    includes_regex=opts.includes_regex,
                    excludes_regex=opts.excludes_regex,
                    scope_analysis=config.scope_analysis,
                    overload_analysis=config.overload_analysis,
                    generated_code_regex=generated_code_regex,
                    generated_code_exts=generated_code_exts,
                    retest_all_regex=retest_all_regex,
                    file_level_regex=file_level_regex,
                    use_cscope=use_cscope,
                )

            logging.info(
                f"Running test selection for {opts.from_revision}..{opts.to_revision} for config {config}"
            )
            included_tests, excluded_tests, selection_causes = rts_algo.select_tests(
                from_revision=opts.from_revision,
                to_revision=opts.to_revision,
            )

            (output_dir / INCLUDED_TESTS_FILE).write_text(
                format_test_list(list(included_tests), simple=opts.simple_output),
                encoding="utf-8"
            )
            (output_dir / EXCLUDED_TESTS_FILE).write_text(
                format_test_list(list(excluded_tests), simple=opts.simple_output),
                encoding="utf-8"
            )
            with (output_dir / SELECTION_CAUSES_FILE).open("w+") as fp:
                json.dump(selection_causes, fp)
        except Exception as e:
            logging.error(f"Error occurred in RTS, falling back to retest-all: {e}")
            (output_dir / INCLUDED_TESTS_FILE).write_text("*\n", encoding="utf-8")
            (output_dir / EXCLUDED_TESTS_FILE).write_text("", encoding="utf-8")
            with (output_dir / SELECTION_CAUSES_FILE).open("w+") as fp:
                json.dump({"*": [SelectionCause.SELECTION_FAILURE.value]}, fp)

        LogEvent(name=f"{RTS_END_EVENT}_{config.name or 'default'}").append(
            log_file=output_dir / EVENT_LOG
        )

    if evaluation:
        for c in [
            RTSConfiguration(
                name=f"{'java' if java else 'cpp'}-func",
                file_level=False,
                scope_analysis=False,
                overload_analysis=False,
                virtual_analysis=False,
                non_functional_analysis=False,
                non_functional_retest_all=False,
            ),
            RTSConfiguration(
                name=f"{'java' if java else 'cpp'}-func-macro",
                file_level=False,
                scope_analysis=False,
                overload_analysis=False,
                virtual_analysis=False,
                non_functional_analysis=True,
                non_functional_retest_all=False,
                non_functional_analysis_depth=non_functional_analysis_depth,
            ),
            RTSConfiguration(
                name=f"{'java' if java else 'cpp'}-func-macro-retest-all",
                file_level=False,
                scope_analysis=False,
                virtual_analysis=False,
                overload_analysis=False,
                non_functional_analysis=False,
                non_functional_retest_all=True,
            ),
            RTSConfiguration(
                name=f"{'java' if java else 'cpp'}-func-scope",
                file_level=False,
                scope_analysis=True,
                overload_analysis=False,
                virtual_analysis=False,
                non_functional_analysis=False,
                non_functional_retest_all=False,
            ),
            RTSConfiguration(
                name=f"{'java' if java else 'cpp'}-func-overload",
                file_level=False,
                scope_analysis=False,
                overload_analysis=True,
                virtual_analysis=False,
                non_functional_analysis=False,
                non_functional_retest_all=False,
            ),
            RTSConfiguration(
                name=f"{'java' if java else 'cpp'}-func-virtual",
                file_level=False,
                scope_analysis=False,
                overload_analysis=False,
                virtual_analysis=True,
                non_functional_analysis=False,
                non_functional_retest_all=False,
            ),
            RTSConfiguration(
                name=f"{'java' if java else 'cpp'}-func-all",
                file_level=False,
                scope_analysis=True,
                overload_analysis=True,
                virtual_analysis=True,
                non_functional_analysis=True,
                non_functional_retest_all=False,
                non_functional_analysis_depth=non_functional_analysis_depth,
            ),
            RTSConfiguration(
                name=f"{'java' if java else 'cpp'}-file",
                file_level=True,
                scope_analysis=False,
                overload_analysis=False,
                virtual_analysis=False,
                non_functional_analysis=False,
                non_functional_retest_all=False,
            ),
        ]:
            _run_rts(config=c)
    else:
        # in the default case, we simply use the provided CLI options
        _run_rts(
            config=RTSConfiguration(
                name="",
                file_level=file_level,
                scope_analysis=scope_analysis,
                overload_analysis=overload_analysis,
                virtual_analysis=virtual_analysis,
                non_functional_analysis=non_functional_analysis,
                non_functional_retest_all=non_functional_retest_all,
                non_functional_analysis_depth=non_functional_analysis_depth,
            )
        )


@app.command()
def syscalls(
    ctx: typer.Context,
    test_file_traces_file: Path = typer.Option(
        ...,
        "--traces",
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
    ),
):
    """
    Select C++ tests for GoogleTesting framework based on opened files for each test.
    """
    opts: SelectCommonOptions = ctx.obj

    LogEvent(name=f"{RTS_START_EVENT}_syscall").append(log_file=opts.output / EVENT_LOG)

    test_file_traces: TestFileTraces
    if has_ext(test_file_traces_file, exts=[".csv"]):
        test_file_traces = TestFileTraces.from_csv(test_file_traces_file)
    elif has_ext(test_file_traces_file, exts=[".pkl"]):
        test_file_traces = TestFileTraces.from_pickle(test_file_traces_file)
    else:
        raise Exception(
            f"Provided invalid test file traces file format, only .csv and .pkl are currently supported."
        )

    rts_algo: RTSAlgo = SyscallFileLevelRTS(
        vcs_client=opts.vcs_client,
        test_file_traces=test_file_traces,
        output_dir=opts.output,
        includes_regex=opts.includes_regex,
        excludes_regex=opts.excludes_regex,
    )
    try:
        included_tests, excluded_tests, selection_causes = rts_algo.select_tests(
            from_revision=opts.from_revision,
            to_revision=opts.to_revision,
        )

        (opts.output / INCLUDED_TESTS_FILE).write_text(
            format_test_list(list(included_tests), simple=opts.simple_output),
            encoding="utf-8"
        )
        (opts.output / EXCLUDED_TESTS_FILE).write_text(
            format_test_list(list(excluded_tests), simple=opts.simple_output),
            encoding="utf-8"
        )
        with (opts.output / SELECTION_CAUSES_FILE).open("w+") as fp:
            json.dump(selection_causes, fp)

        LogEvent(name=f"{RTS_END_EVENT}_syscall").append(
            log_file=opts.output / EVENT_LOG
        )

    except Exception as e:
        logging.error(f"Error occurred in RTS, falling back to retest-all: {e}")
        (opts.output / INCLUDED_TESTS_FILE).write_text("*\n", encoding="utf-8")
        (opts.output / EXCLUDED_TESTS_FILE).write_text("", encoding="utf-8")
        with (opts.output / SELECTION_CAUSES_FILE).open("w+") as fp:
            json.dump({"*": [SelectionCause.SELECTION_FAILURE.value]}, fp)
