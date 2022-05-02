#!/usr/bin/env python3
# -*- coding: utf8 -*-

# flake8: noqa           # flake8 has no per file settings :(
# pylint: disable=C0111  # docstrings are always outdated and wrong
# pylint: disable=C0114  #      Missing module docstring (missing-module-docstring)
# pylint: disable=W0511  # todo is encouraged
# pylint: disable=C0301  # line too long
# pylint: disable=R0902  # too many instance attributes
# pylint: disable=C0302  # too many lines in module
# pylint: disable=C0103  # single letter var names, func name too descriptive
# pylint: disable=R0911  # too many return statements
# pylint: disable=R0912  # too many branches
# pylint: disable=R0915  # too many statements
# pylint: disable=R0913  # too many arguments
# pylint: disable=R1702  # too many nested blocks
# pylint: disable=R0914  # too many local variables
# pylint: disable=R0903  # too few public methods
# pylint: disable=E1101  # no member for base
# pylint: disable=W0201  # attribute defined outside __init__
# pylint: disable=R0916  # Too many boolean expressions in if statement
# pylint: disable=C0305  # Trailing newlines editor should fix automatically, pointless warning

import glob
import logging
import os
import sys
from math import inf
from pathlib import Path
from signal import SIG_DFL
from signal import SIGPIPE
from signal import signal
# from typing import Tuple
# from typing import List
from typing import Optional
from typing import Sequence
from typing import Union

import click
import sh
# from eprint import eprint
from asserttool import ic
# from asserttool import validate_slice
from clicktool import click_add_options
from clicktool import click_global_options
from clicktool import tv
# from mptool import unmp
from mathtool import sort_versions
from mptool import output
from pathtool import write_line_to_file

# from retry_on_exception import retry_on_exception
# from timetool import get_timestamp

signal(SIGPIPE, SIG_DFL)


def portage_categories():
    categories_path = (
        Path(str(sh.portageq("get_repo_path", "/", "gentoo").strip()))
        / Path("profiles")
        / Path("categories")
    )
    with open(categories_path, "r") as fh:
        lines = fh.readlines()
    categories = [c.strip() for c in lines]
    categories.append("dev-zig")
    del lines
    del categories_path
    return categories


def get_latest_postgresql_version(
    verbose: Union[bool, int, float],
):
    glob_pattern = "/etc/init.d/postgresql-*"
    if verbose:
        ic(glob_pattern)
    results = glob.glob(glob_pattern)
    if verbose:
        ic(results)
    if len(results) == 0:
        raise FileNotFoundError(glob_pattern)
    versions = [init.split("-")[-1] for init in results]
    if verbose:
        ic(versions)
    versions = sort_versions(versions, verbose=verbose)
    if verbose:
        ic(versions)

    return versions[0]


def get_use_flags_for_package(
    package: str,
    *,
    verbose: Union[bool, int, float],
):

    result = sh.cat(sh.equery("uses", package, _piped=True))
    result = result.strip()
    if verbose:
        ic(result)
    result = [r[1:] for r in result.split("\n")]

    return result


## broken, equery check > bla fails
# def resolve_and_check_package_name(package: str,
#                                   *,
#                                   verbose: Union[bool, int, float],
#                                   ):
#
#    #result = sh.cat(sh.equery('check', package, _piped=True))
#    result = sh.equery('check', package,)
#    result = result.strip()
#    if verbose:
#        ic(result)
#    #result = [r[1:] for r in result.split('\n')]
#
#    return result


def resolve_package_name(
    package: str,
    *,
    verbose: Union[bool, int, float],
) -> str:

    # result = sh.cat(sh.equery('check', package, _piped=True))
    result = sh.equery(
        "--quiet",
        "list",
        package,
    )
    result = result.strip()
    if verbose:
        ic(result)
    # result = [r[1:] for r in result.split('\n')]
    return result


def get_python_dependency(
    package: str,
    *,
    verbose: Union[bool, int, float],
) -> bool:

    result = sh.equery(
        "--quiet",
        "uses",
        package,
    )
    result = result.strip()
    for line in result.splitlines():
        if verbose:
            ic(line)
        if line.startswith(b"+python_targets_python"):
            return True
    return False


def generate_ebuild_dependency_line(
    package: str,
    *,
    verbose: Union[bool, int, float],
):
    package = resolve_package_name(
        package,
        verbose=verbose,
    )
    line = f"\t{package}"
    if get_python_dependency(
        package,
        verbose=verbose,
    ):
        line += "[${PYTHON_USEDEP}]"

    if verbose:
        ic(line)
    return line


def install_packages(
    packages: Sequence[str],
    *,
    verbose: Union[bool, int, float],
) -> None:
    # if verbose:
    #    logging.basicConfig(level=logging.INFO)

    emerge_command = sh.emerge.bake(
        "--with-bdeps=y",
        "-v",
        "--tree",
        "--usepkg=n",
        "-u",
        "--ask",
        "n",
        "--noreplace",
    )
    for package in packages:
        ic(package)
        emerge_command = emerge_command.bake(package)

    ic(package)
    emerge_command("-p", _out=sys.stdout, _err=sys.stderr)
    emerge_command(_out=sys.stdout, _err=sys.stderr)


def install_packages_force(
    packages: Sequence[str],
    *,
    upgrade_only: bool = False,
    verbose: Union[bool, int, float],
) -> None:

    if verbose:
        logging.basicConfig(level=logging.INFO)
    _env = os.environ.copy()
    _env["CONFIG_PROTECT"] = "-*"

    if verbose:
        ic(packages, upgrade_only)

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

    if upgrade_only:
        emerge_command = emerge_command.bake("-u")

    for package in packages:
        emerge_command = emerge_command.bake(package)

    emerge_command("-p", _ok_code=[0, 1], _env=_env, _out=sys.stdout, _err=sys.stderr)
    emerge_command(
        "--quiet", "--autounmask-continue", _env=_env, _out=sys.stdout, _err=sys.stderr
    )


def add_accept_keyword(
    package: str,
    *,
    verbose: Union[bool, int, float],
) -> None:

    line = f"={package} **"
    if verbose:
        ic(line)
    write_line_to_file(
        path=Path("/etc/portage/package.accept_keywords"),
        line=line + "\n",
        unique=True,
        verbose=verbose,
    )


@click.group(no_args_is_help=True)
@click_add_options(click_global_options)
@click.pass_context
def cli(
    ctx,
    verbose: Union[bool, int, float],
    verbose_inf: bool,
    dict_input: bool,
) -> None:
    tty, verbose = tv(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
    )


@cli.command()
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def use_flags_for_package(
    ctx,
    package: str,
    verbose: Union[bool, int, float],
    verbose_inf: bool,
    dict_input: bool,
) -> None:
    tty, verbose = tv(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
    )

    if not package.startswith("@"):
        assert "/" in package
    flags = get_use_flags_for_package(
        package=package,
        verbose=verbose,
    )
    for flag in flags:
        output(
            flag.encode("utf8"),  # hm.
            reason=package,
            dict_input=dict_input,
            tty=tty,
            verbose=verbose,
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
    verbose: Union[bool, int, float],
    verbose_inf: bool,
    dict_input: bool,
) -> None:
    tty, verbose = tv(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
    )

    valid_flags = get_use_flags_for_package(
        package=package,
        verbose=verbose,
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
    verbose: Union[bool, int, float],
    verbose_inf: bool,
    dict_input: bool,
) -> None:
    tty, verbose = tv(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
    )

    if not package.startswith("@"):
        assert "/" in package
    sh_oet = {"_out": sys.stdout, "_err": sys.stderr, "_tee": True}

    package = Path(
        sh.equery("-q", "list", package, **sh_oet).stdout.decode("utf8").strip()
    )
    ic(package)
    package_location_command = sh.equery("-q", "meta", package, **sh_oet)
    package_location_command_stdout = package_location_command.stdout.splitlines()
    package_location = None
    for line in package_location_command_stdout:
        if line.startswith(b"Location: "):
            package_location = line.split(b":")[-1].strip()

    if not package_location:
        raise FileNotFoundError(package_location_command_stdout)
    ic(package_location)

    package_name_and_version = package.name
    ebuild_path = Path(os.fsdecode(package_location)) / Path(
        os.fsdecode(package_name_and_version + ".ebuild")
    )
    ic(ebuild_path)

    ebuild_clean_command = sh.sudo.ebuild(
        ebuild_path,
        "clean",
        _fg=True,
    )
    ebuild_unpack_command = sh.sudo.ebuild(
        ebuild_path,
        "unpack",
        _fg=True,
    )
    # ebuild_unpack_command_stdout = ebuild_unpack_command.stdout.splitlines()
    # ic(ebuild_unpack_command_stdout)
    ebuild_prepare_command = sh.sudo.ebuild(
        ebuild_path,
        "prepare",
        _fg=True,
    )
    ebuild_configure_command = sh.sudo.ebuild(
        ebuild_path,
        "configure",
        _fg=True,
    )
    work_dir = Path("/var/tmp/portage") / package / Path("work")
    ic(work_dir)
    sh.sudo.chmod("-R", "a+rx", work_dir.parent, _fg=True)


@cli.command()
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def files_provided_by_package(
    ctx,
    package: str,
    verbose: Union[bool, int, float],
    verbose_inf: bool,
    dict_input: bool,
) -> None:
    tty, verbose = tv(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
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
    qlist_command = qlist_command(_tee=not tty, **_oe, **_tty_out)
    if tty:
        return

    qlist_stdout_lines = qlist_command.stdout.splitlines()

    for line in qlist_stdout_lines:
        if (
            verbose == inf
        ):  # `verbose: int >= math inf` debug protocol works  #inf has always been a float... all `verbose: int` type annotations are wrong
            ic(line)
        output(line, reason=None, dict_input=dict_input, tty=tty, verbose=verbose)


@click.command()
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def emerge_keepwork(
    ctx,
    package: str,
    verbose: Union[bool, int, float],
    verbose_inf: bool,
    dict_input: bool,
) -> None:
    tty, verbose = tv(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
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
@click.argument("package", type=str, nargs=1)
@click.option("--force-use", is_flag=True)
@click.option("--upgrade-only", is_flag=True)
@click_add_options(click_global_options)
@click.pass_context
def _install_package(
    ctx,
    package: str,
    verbose: Union[bool, int, float],
    verbose_inf: bool,
    dict_input: bool,
    force_use: bool,
    upgrade_only: bool,
) -> None:
    if not package.startswith("@"):
        assert "/" in package
    tty, verbose = tv(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
    )

    if force_use:
        install_packages_force(
            packages=(package,), verbose=verbose, upgrade_only=upgrade_only
        )
    else:
        install_packages(
            packages=(package,),
            verbose=verbose,
        )


@cli.command("resolve")
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def _resolve_package(
    ctx,
    package: str,
    verbose: Union[bool, int, float],
    verbose_inf: bool,
    dict_input: bool,
) -> None:
    if not package.startswith("@"):
        assert "/" in package
    tty, verbose = tv(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
    )

    result = resolve_package_name(
        package=package,
        verbose=verbose,
    )
    output(result, reason=package, dict_input=dict_input, tty=tty, verbose=verbose)
