#!/usr/bin/env python3

import os
import sys
from collections.abc import Iterator
from pathlib import Path
from signal import SIG_DFL
from signal import SIGPIPE
from signal import signal

import click
import hs
import portage
from portage.dep import Atom
from portage.dep import dep_getkey
from portage.dep import use_reduce
from portage.versions import cpv_getkey
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


def _portdb():
    return portage.db[portage.root]["porttree"].dbapi


def _vardb():
    return portage.db[portage.root]["vartree"].dbapi


def _strip_version(atom: str) -> str:
    # cpv_getkey is portage's own parser; it returns the input unchanged when
    # there is no version to strip
    return cpv_getkey(atom) or atom


def qualify_package(package: str) -> str:
    # returns unchanged if already qualified (cat/name), an atom set (@name),
    # or a versioned/operator atom; otherwise resolves the unique cat/name
    # against the installed packages first, then the whole tree
    if (
        package.startswith("@")
        or "/" in package
        or package.startswith(("=", ">", "<", "~", "!"))
    ):
        return package

    matches: set[str] = set()
    for db in (_vardb(), _portdb()):
        matches = {cp for cp in db.cp_all() if cp.split("/", 1)[1] == package}
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
    return bool(_vardb().match(pkg))


def portage_categories() -> list[str]:
    categories = list(portage.settings.categories)
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
    vdb = _vardb()
    installed = vdb.match(package)
    if not installed:
        raise click.ClickException(f"'{package}' is not installed")
    use, iuse = vdb.aux_get(installed[0], ["USE", "IUSE"])
    enabled = set(use.split())
    flags = []
    for flag in sorted({f.lstrip("+-") for f in iuse.split()}):
        flags.append(flag if flag in enabled else f"-{flag}")
    return flags


def resolve_package_name(package: str) -> str:
    package = _qualify_atom(package)
    result = _portdb().xmatch("bestmatch-visible", package)
    if not result:
        raise click.ClickException(f"No visible package matches '{package}'")
    ic(result)
    return result


def get_python_dependency(package: str) -> bool:
    package = qualify_package(package)
    cpv = _portdb().xmatch("bestmatch-visible", package)
    if not cpv:
        return False
    (iuse,) = _portdb().aux_get(cpv, ["IUSE"])
    return any(f.lstrip("+-").startswith("python_targets_python") for f in iuse.split())


def generate_ebuild_dependency_line(package: str) -> str:
    package = resolve_package_name(package)
    line = f"\t{package}"
    if get_python_dependency(package):
        line += "[${PYTHON_USEDEP}]"
    ic(line)
    return line



def dependency_closure(
    atom: str,
    *,
    build_deps: bool = True,
) -> set[str]:
    # Walks DEPEND/RDEPEND/BDEPEND transitively via the portage API, resolving
    # each atom to its best visible version. This answers "which packages does
    # building this pull in" without shelling out to emerge, and returns
    # cat/pkg keys rather than versioned cpvs.
    portdb = _portdb()
    settings = portage.settings
    wants = ["DEPEND", "RDEPEND", "BDEPEND"] if build_deps else ["RDEPEND"]

    seen: set[str] = set()
    pending = [_qualify_atom(atom)]
    while pending:
        current = pending.pop()
        cpv = portdb.xmatch("bestmatch-visible", current)
        if not cpv:
            continue
        key = cpv_getkey(cpv)
        if key in seen:
            continue
        seen.add(key)

        use = settings.get("USE", "").split()
        for depstr in portdb.aux_get(cpv, wants):
            if not depstr:
                continue
            for dep in use_reduce(
                depstr,
                uselist=use,
                opconvert=False,
                flat=True,
                token_class=Atom,
                is_valid_flag=lambda _flag: True,
            ):
                if dep in ("||", "(", ")"):
                    continue
                dep_key = dep_getkey(str(dep))
                if dep_key.startswith("!"):
                    continue
                if dep_key not in seen:
                    pending.append(dep_key)

    ic(len(seen))
    return seen


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
    yield from sorted(_vardb().cpv_all())


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

    cpv = _portdb().xmatch("bestmatch-visible", package)
    if not cpv:
        raise click.ClickException(f"No visible package matches '{package}'")
    ebuild_path = _portdb().findname(cpv)
    if not ebuild_path:
        raise click.ClickException(f"No ebuild found for '{cpv}'")
    package_location = Path(ebuild_path).parent.as_posix()
    icp(package_location)

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

    vdb = _vardb()
    installed = vdb.match(package)
    if not installed:
        raise click.ClickException(f"'{package}' is not installed")
    files = sorted(vdb._dblink(installed[0]).getcontents())
    if tty:
        for line in files:
            print(line)
        return

    for line in files:
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


@cli.command("dependency-closure")
@click.argument("atom", type=str, nargs=1)
@click.option("--runtime-only", is_flag=True)
@click_add_options(click_global_options)
@click.pass_context
def _dependency_closure(
    ctx: click.Context,
    atom: str,
    runtime_only: bool,
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

    for package in sorted(dependency_closure(atom, build_deps=not runtime_only)):
        output(
            package,
            reason=atom,
            dict_output=dict_output,
            tty=tty,
        )
