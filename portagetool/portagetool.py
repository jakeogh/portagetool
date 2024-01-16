#!/usr/bin/env python3
# -*- coding: utf8 -*-

# pylint: disable=missing-docstring               # [C0111] docstrings are always outdated and wrong
# pylint: disable=missing-module-docstring        # [C0114]
# pylint: disable=fixme                           # [W0511] todo is encouraged
# pylint: disable=line-too-long                   # [C0301]
# pylint: disable=too-many-instance-attributes    # [R0902]
# pylint: disable=too-many-lines                  # [C0302] too many lines in module
# pylint: disable=invalid-name                    # [C0103] single letter var names, name too descriptive
# pylint: disable=too-many-return-statements      # [R0911]
# pylint: disable=too-many-branches               # [R0912]
# pylint: disable=too-many-statements             # [R0915]
# pylint: disable=too-many-arguments              # [R0913]
# pylint: disable=too-many-nested-blocks          # [R1702]
# pylint: disable=too-many-locals                 # [R0914]
# pylint: disable=too-few-public-methods          # [R0903]
# pylint: disable=no-member                       # [E1101] no member for base
# pylint: disable=attribute-defined-outside-init  # [W0201]
# pylint: disable=too-many-boolean-expressions    # [R0916] in if statement
from __future__ import annotations

import glob
import logging
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from signal import SIG_DFL
from signal import SIGPIPE
from signal import signal

import click
import sh
from asserttool import ic
from asserttool import icp
from click_auto_help import AHGroup
from clicktool import click_add_options
from clicktool import click_global_options
from clicktool import tvicgvd
from globalverbose import gvd
from mathtool import sort_versions
from mptool import output
from pathtool import write_line_to_file

# from retry_on_exception import retry_on_exception
# from timestamptool import get_timestamp

signal(SIGPIPE, SIG_DFL)

logging.basicConfig(level=logging.INFO)


def package_atom_installed(pkg):
    _c = sh.Command("qlist")
    _c = _c.bake("-ICve", pkg)
    try:
        _c()
    except sh.ErrorReturnCode_1:
        return False
    return True


def portage_categories():
    categories_path = (
        Path(str(sh.portageq("get_repo_path", "/", "gentoo").strip()))
        / Path("profiles")
        / Path("categories")
    )
    with open(categories_path, "r", encoding="utf8") as fh:
        lines = fh.readlines()
    categories = [c.strip() for c in lines]
    categories.append("dev-zig")
    del lines
    del categories_path
    return categories


def get_latest_postgresql_version(
    verbose: bool = False,
):
    glob_pattern = "/etc/init.d/postgresql-*"
    ic(glob_pattern)
    results = glob.glob(glob_pattern)
    ic(results)
    if len(results) == 0:
        raise FileNotFoundError(glob_pattern)
    versions = [init.split("-")[-1] for init in results]
    ic(versions)
    versions = sort_versions(versions)
    ic(versions)

    return versions[0]


def get_use_flags_for_package(
    package: str,
    *,
    verbose: bool = False,
):
    # icp(package)
    # result = sh.cat(sh.equery("uses", package, _piped=True))
    result = sh.equery("uses", package, _tty_out=False)
    result = result.strip()
    # icp(result)
    result = [r[1:] for r in result.split("\n")]

    # icp(result)
    return result


# broken, equery check > bla fails
# def resolve_and_check_package_name(package: str,
#                                   *,
#                                   verbose: bool = False,
#                                   ):
#
#    #result = sh.cat(sh.equery('check', package, _piped=True))
#    result = sh.equery('check', package,)
#    result = result.strip()
#    ic(result)
#    #result = [r[1:] for r in result.split('\n')]
#
#    return result


def resolve_package_name(
    package: str,
    *,
    verbose: bool = False,
) -> str:
    # result = sh.cat(sh.equery('check', package, _piped=True))
    result = sh.equery(
        "--quiet",
        "list",
        package,
    )
    result = result.strip()
    ic(result)
    # result = [r[1:] for r in result.split('\n')]
    return result


def get_python_dependency(
    package: str,
    *,
    verbose: bool = False,
) -> bool:
    result = sh.equery(
        "--quiet",
        "uses",
        package,
    )
    result = result.strip()
    for line in result.splitlines():
        ic(line)
        if line.startswith(b"+python_targets_python"):
            return True
    return False


def generate_ebuild_dependency_line(
    package: str,
    *,
    verbose: bool = False,
):
    package = resolve_package_name(
        package,
    )
    line = f"\t{package}"
    if get_python_dependency(
        package,
    ):
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
    verbose: bool = False,
):
    install_packages(
        packages=(package,),
        force=force,
        upgrade_only=True,
        nice=nice,
        oneshot=oneshot,
        noreplace=noreplace,
    )


def installed_packages(
    verbose: bool = False,
) -> Iterator[str]:
    qlist_command = sh.qlist.bake("-IRCv")
    _results = qlist_command().strip().split("\n")
    for _result in _results:
        yield _result


def install_packages(
    packages: tuple[str, ...] | list[str],
    *,
    force: bool,
    upgrade_only: bool = False,
    nice: bool = False,
    oneshot: bool = False,
    noreplace: bool = False,
    verbose: bool = False,
) -> None:
    ic(packages, upgrade_only)

    _env = os.environ.copy()

    if not nice:
        _env["PORTAGE_NICENESS"] = "-2"
        _env["PORTAGE_IONICE_COMMAND"] = ""
        _env["PORTAGE_SCHEDULING_POLICY"] = "other"

    if force:
        _env["CONFIG_PROTECT"] = "-*"

        emerge_command = sh.emerge.bake(
            "-v",
            "--with-bdeps=y",
            "--tree",
            "--usepkg=n",
            "--ask",
            "n",
            "--autounmask",
            "--autounmask-write",
        )

        if noreplace:
            emerge_command = emerge_command.bake("--noreplace")

        if oneshot:
            emerge_command = emerge_command.bake("--oneshot")

        if upgrade_only:
            emerge_command = emerge_command.bake("-u")

        package = None
        for package in packages:
            emerge_command = emerge_command.bake(package)

        emerge_command(
            "-p", _ok_code=[0, 1], _env=_env, _out=sys.stdout, _err=sys.stderr
        )
        emerge_command(
            "--quiet",
            "--autounmask-continue",
            _env=_env,
            _out=sys.stdout,
            _err=sys.stderr,
        )
    else:
        emerge_command = sh.emerge.bake(
            "--with-bdeps=y",
            "-v",
            "--tree",
            "--usepkg=n",
            "--ask",
            "n",
        )

        if noreplace:
            emerge_command = emerge_command.bake("--noreplace")

        if oneshot:
            emerge_command = emerge_command.bake("--oneshot")

        if upgrade_only:
            emerge_command = emerge_command.bake("-u")

        package = None
        for package in packages:
            ic(package)
            emerge_command = emerge_command.bake(package)

        if package:
            ic(package)
            emerge_command("-p", _out=sys.stdout, _err=sys.stderr)
            emerge_command(_out=sys.stdout, _err=sys.stderr)


def mask_package(
    package: str,
    *,
    verbose: bool = False,
) -> None:
    line = f"{package}"
    _pkg = package.split("/")[-1]
    ic(line)
    write_line_to_file(
        path=Path(f"/etc/portage/package.mask/{_pkg}"),
        line=line + "\n",
        unique=True,
    )


def add_accept_keyword(
    package: str,
    *,
    verbose: bool = False,
) -> None:
    line = f"={package} **"
    _pkg = package.split("/")[-1]
    ic(line)
    try:
        write_line_to_file(
            path=Path("/etc/portage/package.accept_keywords"),
            line=line + "\n",
            unique=True,
        )
    except IsADirectoryError:
        write_line_to_file(
            path=Path("/etc/portage/package.accept_keywords") / Path(_pkg),
            line=line + "\n",
            unique=True,
        )


@click.group(no_args_is_help=True, cls=AHGroup)
@click_add_options(click_global_options)
@click.pass_context
def cli(
    ctx,
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
    ctx,
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

    latest = get_latest_postgresql_version()
    output(
        latest,
        reason=None,
        dict_output=dict_output,
        tty=tty,
    )


@cli.command("mask-package")
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def _mask_package(
    ctx,
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

    if not package.startswith("@"):
        assert "/" in package

    mask_package(package=package)


@cli.command()
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def use_flags_for_package(
    ctx,
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

    if not package.startswith("@"):
        assert "/" in package
    flags = get_use_flags_for_package(
        package=package,
    )
    for flag in flags:
        output(
            flag.encode("utf8"),  # hm.
            reason=package,
            dict_output=dict_output,
            tty=tty,
        )


@cli.command()
@click.argument("package", type=str, nargs=1)
@click.argument("flag", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def set_use_flag_for_package(
    ctx,
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

    valid_flags = get_use_flags_for_package(
        package=package,
    )

    if not package.startswith("@"):
        assert "/" in package
    raw_flag = flag
    if flag.startswith("-"):
        raw_flag = flag[1:]

    assert raw_flag in valid_flags

    assert False


@cli.command()
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def generate_patched_package_source(
    ctx,
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

    if not package.startswith("@"):
        assert "/" in package
    sh_oet = {"_out": sys.stdout, "_err": sys.stderr, "_tee": True}

    # package = Path(sh.equery("-q", "list", package, **sh_oet).strip())
    package = Path(package)  # pathlib abuse, but works nice
    icp(package)
    package_location_command = sh.equery("-q", "meta", package, **sh_oet).strip()
    package_location_command_stdout = package_location_command.splitlines()
    package_location = None
    for line in package_location_command_stdout:
        if line.startswith("Location: "):
            package_location = line.split(":")[-1].strip()

    if not package_location:
        raise FileNotFoundError(package_location_command_stdout)
    ic(package_location)

    package_name_and_version = package.name
    ebuild_path = Path(os.fsdecode(package_location)) / Path(
        os.fsdecode(package_name_and_version + ".ebuild")
    )
    ic(ebuild_path)

    ebuild_clean_command = sh.ebuild(
        ebuild_path,
        "clean",
        _fg=True,
    )
    ebuild_unpack_command = sh.ebuild(
        ebuild_path,
        "unpack",
        _fg=True,
    )
    ebuild_prepare_command = sh.ebuild(
        ebuild_path,
        "prepare",
        _fg=True,
    )
    ebuild_configure_command = sh.ebuild(
        ebuild_path,
        "configure",
        _fg=True,
    )
    work_dir = Path("/var/tmp/portage") / package / Path("work")
    ic(work_dir)
    sh.chmod("-R", "a+rx", work_dir.parent, _fg=True)


@cli.command()
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def files_provided_by_package(
    ctx,
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

    qlist_command = sh.Command("qlist")
    qlist_command = qlist_command.bake("--exact", package)

    if not package.startswith("@"):
        assert "/" in package
    _tty_out = {}
    _oe = {}
    if not tty:
        _tty_out = {"_tty_out": False}
    if tty:
        _oe = {
            "_out": sys.stdout,
            "_err": sys.stderr,
        }
    icp(tty, _tty_out, _oe)
    qlist_command = qlist_command(_tee=not tty, **_oe, **_tty_out).strip()
    if tty:
        return

    qlist_stdout_lines = qlist_command.splitlines()

    for line in qlist_stdout_lines:
        if gvd:
            ic(line)
        output(line, reason=None, dict_output=dict_output, tty=tty)


@click.command()
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def emerge_keepwork(
    ctx,
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
    if not package.startswith("@"):
        assert "/" in package

    sh.emerge(
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
    ctx,
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

    for package in packages:
        if not package.startswith("@"):
            assert "/" in package

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
    ctx,
    package: str,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool = False,
) -> None:
    if not package.startswith("@"):
        assert "/" in package
    tty, verbose = tvicgvd(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
        ic=ic,
        gvd=gvd,
    )

    result = resolve_package_name(
        package=package,
    )
    output(
        result,
        reason=package,
        dict_output=dict_output,
        tty=tty,
    )


@cli.command("list")
@click_add_options(click_global_options)
@click.pass_context
def _list(
    ctx,
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

    results = installed_packages()
    for _ in results:
        output(
            _,
            reason=None,
            dict_output=dict_output,
            tty=tty,
        )
