#!/usr/bin/env python3

import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from signal import SIG_DFL
from signal import SIGPIPE
from signal import signal

import click
import hs
from asserttool import ic
from asserttool import icp
from click_auto_help import AHGroup
from clicktool import click_add_options
from clicktool import click_global_options
from clicktool import tvicgvd
from filetool import ensure_line_in_config_file
from globalverbose import gvd
from mathtool import sort_versions
from mptool import output

signal(SIGPIPE, SIG_DFL)


# Portage version suffix on a cat/name-ver atom: leading `-`, then version per PMS-ish.
_VER_RE = re.compile(
    r"-(\d+(?:\.\d+)*[a-z]?(?:_(?:alpha|beta|pre|rc|p)\d*)*(?:-r\d+)?)$"
)


def _strip_version(atom: str) -> str:
    m = _VER_RE.search(atom)
    return atom[: m.start()] if m else atom


def qualify_package(package: str) -> str:
    # returns unchanged if already qualified (cat/name), an atom set (@name),
    # or a versioned/operator atom; otherwise resolves the unique cat/name via
    # equery (installed first, then tree and overlays)
    if (
        package.startswith("@")
        or "/" in package
        or package.startswith(("=", ">", "<", "~", "!"))
    ):
        return package

    matches: set[str] = set()
    for extra in ([], ["-ipo"]):
        try:
            result = str(
                hs.Command("equery")("--quiet", "list", *extra, package, _tty_out=False)
            )
        except hs.ErrorReturnCode:
            result = ""
        for line in result.splitlines():
            line = line.strip()
            if not line:
                continue
            line = line.split(":", 1)[0]  # drop slot/repo suffix
            cat_name = _strip_version(line)
            if "/" in cat_name:
                matches.add(cat_name)
        if matches:
            break

    if not matches:
        raise click.ClickException(f"No package matches '{package}'")
    if len(matches) > 1:
        lines = [f"Package name '{package}' is ambiguous. Possibilities:"]
        lines.extend(f"  {m}" for m in sorted(matches))
        raise click.ClickException("\n".join(lines))

    resolved = next(iter(matches))
    if resolved != package:
        ic(package, resolved)
    return resolved


def _qualify_atom(package: str) -> str:
    # like qualify_package, but preserves a trailing -version on bare input
    if (
        package.startswith("@")
        or "/" in package
        or package.startswith(("=", ">", "<", "~", "!"))
    ):
        return package
    name = _strip_version(package)
    if name != package:
        return qualify_package(name) + package[len(name) :]
    return qualify_package(package)


def package_atom_installed(pkg: str) -> bool:
    _c = hs.Command("qlist")
    _c.bake("-ICve", pkg)
    try:
        _c()
    except hs.ErrorReturnCode_1:
        return False
    return True


def portage_categories() -> list[str]:
    categories_path = (
        Path(str(hs.Command("portageq")("get_repo_path", "/", "gentoo")).strip())
        / "profiles"
        / "categories"
    )
    with open(categories_path, "r", encoding="utf8") as fh:
        categories = [c.strip() for c in fh.readlines()]
    categories.append("dev-zig")
    return categories


def get_latest_postgresql_version() -> str:
    results = sorted(Path("/etc/init.d").glob("postgresql-*"))
    ic(results)
    if not results:
        raise FileNotFoundError("/etc/init.d/postgresql-*")
    versions = [init.name.split("-")[-1] for init in results]
    versions = sort_versions(versions)
    ic(versions)
    return versions[0]


def get_use_flags_for_package(package: str) -> list[str]:
    package = qualify_package(package)
    result = str(hs.Command("equery")("uses", package, _tty_out=False)).strip()
    return [r[1:] for r in result.split("\n")]


def resolve_package_name(package: str) -> str:
    package = _qualify_atom(package)
    result = str(
        hs.Command("equery")(
            "--quiet",
            "list",
            package,
        )
    ).strip()
    ic(result)
    return result


def get_python_dependency(package: str) -> bool:
    package = qualify_package(package)
    result = str(
        hs.Command("equery")(
            "--quiet",
            "uses",
            package,
        )
    ).strip()
    for line in result.splitlines():
        ic(line)
        if line.startswith("+python_targets_python"):
            return True
    return False


def generate_ebuild_dependency_line(package: str) -> str:
    package = resolve_package_name(package)
    line = f"\t{package}"
    if get_python_dependency(package):
        line += "[${PYTHON_USEDEP}]"
    ic(line)
    return line


def install(
    package: str,
    *,
    force: bool = False,
    nice: bool = False,
    oneshot: bool = False,
    noreplace: bool = False,
) -> None:
    install_packages(
        packages=(package,),
        force=force,
        upgrade_only=True,
        nice=nice,
        oneshot=oneshot,
        noreplace=noreplace,
    )


def installed_packages() -> Iterator[str]:
    qlist_command = hs.Command("qlist")
    qlist_command.bake("-IRCv")
    yield from str(qlist_command()).strip().split("\n")


def install_packages(
    packages: tuple[str, ...] | list[str],
    *,
    force: bool,
    upgrade_only: bool = False,
    nice: bool = False,
    oneshot: bool = False,
    noreplace: bool = False,
) -> None:
    packages = tuple(_qualify_atom(p) for p in packages)
    ic(packages, upgrade_only)

    _env = os.environ.copy()

    if not nice:
        _env["PORTAGE_NICENESS"] = "-2"
        _env["PORTAGE_IONICE_COMMAND"] = ""
        _env["PORTAGE_SCHEDULING_POLICY"] = "other"

    emerge_command = hs.Command("emerge")
    emerge_command.bake(
        "-v",
        "--with-bdeps=y",
        "--tree",
        "--usepkg=n",
        "--ask",
        "n",
    )

    if force:
        _env["CONFIG_PROTECT"] = "-*"
        emerge_command.bake(
            "--autounmask",
            "--autounmask-write",
        )

    if noreplace:
        emerge_command.bake("--noreplace")
    if oneshot:
        emerge_command.bake("--oneshot")
    if upgrade_only:
        emerge_command.bake("-u")

    for package in packages:
        ic(package)
        emerge_command.bake(package)

    if not packages:
        return

    if force:
        emerge_command(
            "-p",
            _ok_code=[0, 1],
            _env=_env,
            _out=sys.stdout,
            _err=sys.stderr,
        )
        emerge_command(
            "--quiet",
            "--autounmask-continue",
            _env=_env,
            _out=sys.stdout,
            _err=sys.stderr,
        )
    else:
        emerge_command("-p", _env=_env, _out=sys.stdout, _err=sys.stderr)
        emerge_command(_env=_env, _out=sys.stdout, _err=sys.stderr)


def mask_package(package: str) -> None:
    package = _qualify_atom(package)
    _pkg = package.split("/")[-1]
    ic(package)
    ensure_line_in_config_file(
        path=Path(f"/etc/portage/package.mask/{_pkg}"),
        line=package,
        comment_marker="#",
        ignore_leading_whitespace=True,
    )


def add_accept_keyword(package: str) -> None:
    package = _qualify_atom(package)
    line = f"={package} **"
    _pkg = package.split("/")[-1]
    ic(line)
    try:
        ensure_line_in_config_file(
            path=Path("/etc/portage/package.accept_keywords"),
            line=line,
            comment_marker="#",
            ignore_leading_whitespace=True,
        )
    except IsADirectoryError:
        ensure_line_in_config_file(
            path=Path("/etc/portage/package.accept_keywords") / _pkg,
            line=line,
            comment_marker="#",
            ignore_leading_whitespace=True,
        )


def set_use_flag_for_package(*, package: str, flag: str) -> None:
    package = qualify_package(package)
    valid_flags = get_use_flags_for_package(package=package)

    package_group, package_name = package.split("/")
    raw_flag = flag.removeprefix("-")

    icp(raw_flag, valid_flags)
    if raw_flag not in valid_flags:
        raise click.ClickException(
            f"USE flag '{raw_flag}' is not valid for {package}. "
            f"Valid flags: {', '.join(sorted(valid_flags))}"
        )

    line = f"{package} {flag}"
    icp(line)
    ensure_line_in_config_file(
        path=Path(f"/etc/portage/package.use/{package_group}/{package_name}"),
        line=line,
        comment_marker="#",
        ignore_leading_whitespace=True,
    )


@click.group(no_args_is_help=True, cls=AHGroup)
@click_add_options(click_global_options)
@click.pass_context
def cli(
    ctx: click.Context,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
) -> None:
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )


@cli.command("get-latest-postgresql-version")
@click_add_options(click_global_options)
@click.pass_context
def _get_latest_postgresql_version(
    ctx: click.Context,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
) -> None:
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )

    output(
        get_latest_postgresql_version(),
        reason=None,
        dict_output=dict_output,
        tty=tty,
    )


@cli.command("mask-package")
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def _mask_package(
    ctx: click.Context,
    package: str,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
) -> None:
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )
    mask_package(package=package)


@cli.command()
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def use_flags_for_package(
    ctx: click.Context,
    package: str,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
) -> None:
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )

    package = qualify_package(package)
    for flag in get_use_flags_for_package(package=package):
        output(
            flag.encode("utf8"),
            reason=package,
            dict_output=dict_output,
            tty=tty,
        )


@cli.command("set-use-flag-for-package")
@click.argument("package", type=str, nargs=1)
@click.argument("flag", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def _set_use_flag_for_package(
    ctx: click.Context,
    package: str,
    flag: str,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
) -> None:
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )

    set_use_flag_for_package(package=package, flag=flag)


@cli.command()
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def generate_patched_package_source(
    ctx: click.Context,
    package: str,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
) -> None:
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )

    package = _qualify_atom(package)

    package_path = Path(package)
    icp(package_path)
    package_location_command = hs.Command("equery")
    package_location_command.bake("-q", "meta", package_path.as_posix())
    icp(package_location_command)
    result = str(
        package_location_command(_out=sys.stdout, _err=sys.stderr, _tee=True)
    )
    package_location = None
    for line in result.strip().splitlines():
        if line.startswith("Location: "):
            package_location = line.split(":")[-1].strip()

    if not package_location:
        raise FileNotFoundError(result)
    ic(package_location)

    ebuild_path = Path(package_location) / (package_path.name + ".ebuild")
    ic(ebuild_path)

    _ebuild = hs.Command("ebuild")
    for phase in ("clean", "unpack", "prepare", "configure"):
        _ebuild(ebuild_path.as_posix(), phase, _fg=True)

    work_dir = Path("/var/tmp/portage") / package_path / "work"
    ic(work_dir)
    hs.Command("chmod")("-R", "a+rx", work_dir.parent.as_posix(), _fg=True)


@cli.command()
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def files_provided_by_package(
    ctx: click.Context,
    package: str,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
) -> None:
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )

    package = qualify_package(package)

    qlist_command = hs.Command("qlist")
    qlist_command.bake("--exact", package)

    _kwargs: dict = {"_tee": not tty}
    if tty:
        _kwargs |= {"_out": sys.stdout, "_err": sys.stderr}
    else:
        _kwargs |= {"_tty_out": False}
    icp(qlist_command)
    qlist_result = str(qlist_command(**_kwargs)).strip()
    if tty:
        return

    for line in qlist_result.splitlines():
        if gvd:
            ic(line)
        output(
            line,
            reason=None,
            dict_output=dict_output,
            tty=tty,
        )


@cli.command()
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def emerge_keepwork(
    ctx: click.Context,
    package: str,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
) -> None:
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )

    package = _qualify_atom(package)
    hs.Command("emerge")(
        "--verbose",
        "--tree",
        "--usepkg=n",
        package,
        _out=sys.stdout,
        _err=sys.stderr,
        _env={"FEATURES": "keepwork"},
    )


@cli.command("install")
@click.argument("packages", type=str, nargs=-1)
@click.option("--force", is_flag=True)
@click.option("--nice", is_flag=True)
@click.option("--oneshot", is_flag=True)
@click.option("--noreplace", is_flag=True)
@click.option("--upgrade-only", is_flag=True)
@click_add_options(click_global_options)
@click.pass_context
def _install_package(
    ctx: click.Context,
    packages: tuple[str, ...],
    verbose_inf: bool,
    dict_output: bool,
    force: bool,
    noreplace: bool,
    nice: bool,
    oneshot: bool,
    upgrade_only: bool,
    verbose: bool = False,
) -> None:
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )

    install_packages(
        packages=packages,
        force=force,
        nice=nice,
        oneshot=oneshot,
        upgrade_only=upgrade_only,
        noreplace=noreplace,
    )


@cli.command("resolve")
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def _resolve_package(
    ctx: click.Context,
    package: str,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
) -> None:
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )

    output(
        resolve_package_name(package=package),
        reason=package,
        dict_output=dict_output,
        tty=tty,
    )


@cli.command("list")
@click_add_options(click_global_options)
@click.pass_context
def _list(
    ctx: click.Context,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
) -> None:
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )

    for _package in installed_packages():
        output(
            _package,
            reason=None,
            dict_output=dict_output,
            tty=tty,
        )
