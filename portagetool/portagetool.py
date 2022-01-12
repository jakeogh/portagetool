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
# pylint: disable=C0413  # TEMP isort issue [wrong-import-position] Import "from pathlib import Path" should be placed at the top of the module [C0413]

import glob
import logging
import os
import sys
import time
from math import inf
from pathlib import Path
from signal import SIG_DFL
from signal import SIGPIPE
from signal import signal
from typing import ByteString
from typing import Generator
from typing import Iterable
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import Union

import click
import sh
from asserttool import eprint
from asserttool import ic
from asserttool import nevd
from asserttool import tv
from asserttool import validate_slice
from clicktool import click_add_options
from clicktool import click_global_options
from enumerate_input import enumerate_input
from mathtool import sort_versions
from pathtool import write_line_to_file
from printtool import output
from retry_on_exception import retry_on_exception
from timetool import get_timestamp

signal(SIGPIPE, SIG_DFL)


def portage_categories():
    categories_path = Path(str(sh.portageq('get_repo_path', '/', 'gentoo').strip())) / Path('profiles') / Path('categories')
    with open(categories_path, 'r') as fh:
        lines = fh.readlines()
    categories = [c.strip() for c in lines]
    categories.append('dev-zig')
    del lines
    del categories_path
    return categories


def get_latest_postgresql_version(verbose=False):
    glob_pattern = "/etc/init.d/postgresql-*"
    if verbose:
        ic(glob_pattern)
    results = glob.glob(glob_pattern)
    if verbose:
        ic(results)
    if len(results) == 0:
        raise FileNotFoundError(glob_pattern)
    versions = [init.split('-')[-1] for init in results]
    if verbose:
        ic(versions)
    versions = sort_versions(versions, verbose=verbose)
    if verbose:
        ic(versions)

    return versions[0]


def get_use_flags_for_package(package: str,
                              *,
                              verbose: Optional[int] = None,
                              ):

    result = sh.cat(sh.equery('u', package, _piped=True))
    result = result.strip()
    if verbose:
        ic(result)
    result = [r[1:] for r in result.split('\n')]

    return result


def install_packages(packages: str,
                     *,
                     verbose: Optional[int] = None,
                     ):
    #if verbose:
    #    logging.basicConfig(level=logging.INFO)

    emerge_command = sh.emerge.bake('--with-bdeps=y', '-v', '--tree', '--usepkg=n', '-u', '--ask', 'n', '--noreplace',)
    for package in packages:
        ic(package)
        emerge_command = emerge_command.bake(package)

    ic(package)
    emerge_command('-p', _out=sys.stdout, _err=sys.stderr)
    emerge_command(_out=sys.stdout, _err=sys.stderr)


def install_packages_force(packages: str,
                           *,
                           upgrade_only: bool = False,
                           verbose: Optional[int] = None,
                           ):

    if verbose:
        logging.basicConfig(level=logging.INFO)
    _env = os.environ.copy()
    _env['CONFIG_PROTECT'] ='-*'

    if verbose:
        ic(packages, upgrade_only)

    emerge_command = sh.emerge.bake('-v', '--with-bdeps=y', '--tree', '--usepkg=n', '--ask', 'n', '--autounmask', '--autounmask-write',)

    if upgrade_only:
        emerge_command = emerge_command.bake('-u')

    for package in packages:
        emerge_command = emerge_command.bake(package)

    emerge_command('-p', _ok_code=[0, 1], _env=_env, _out=sys.stdout, _err=sys.stderr)
    emerge_command('--quiet','--autounmask-continue', _env=_env, _out=sys.stdout, _err=sys.stderr)


def add_accept_keyword(package: str,
                       *,
                       verbose: Optional[int] = None,
                       ):

    line = f"={package} **"
    if verbose:
        ic(line)
    write_line_to_file(path=Path('/etc/portage/package.accept_keywords'),
                       line=line + '\n',
                       unique=True,
                       verbose=verbose,
                       )


#def set_use_flag(package: str,
#                 *,
#                 enable: bool,
#                 verbose: Optional[int] = None,
#                 ):
#
#    assert '/' in package
#    assert Path('/etc/portage/package.use').is_dir()
#    destination = Path(get_timestamp() + '__' + package.replace('/', '__'))
#    with open(destination, 'x') as fh:
#        ic(destination)
#



@click.group()
@click_add_options(click_global_options)
@click.pass_context
def cli(ctx,
        verbose: int,
        verbose_inf: bool,
        ):
    tty, verbose = tv(ctx=ctx,
                      verbose=verbose,
                      verbose_inf=verbose_inf,
                      )

@cli.command()
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def use_flags_for_package(ctx,
                          package: str,
                          verbose: int,
                          verbose_inf: bool,
                          ):
    tty, verbose = tv(ctx=ctx,
                      verbose=verbose,
                      verbose_inf=verbose_inf,
                      )

    flags = get_use_flags_for_package(package=package, verbose=verbose,)
    for flag in flags:
        output(flag.encode('utf8'), tty=tty, verbose=verbose)


@cli.command()
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def generate_patched_package_source(ctx,
                                    package: str,
                                    verbose: int,
                                    verbose_inf: bool,
                                    ):
    tty, verbose = tv(ctx=ctx,
                      verbose=verbose,
                      verbose_inf=verbose_inf,
                      )

    sh_oet = {'_out': sys.stdout, '_err': sys.stderr, '_tee': True}

    package = Path(sh.equery('-q', 'list', package, **sh_oet).stdout.decode('utf8').strip())
    ic(package)
    package_location_command = sh.equery('-q', 'meta', package, **sh_oet)
    package_location_command_stdout = package_location_command.stdout.splitlines()
    package_location = None
    for line in package_location_command_stdout:
        if line.startswith(b'Location: '):
            package_location = line.split(b':')[-1].strip()

    if not package_location:
        raise FileNotFoundError(package_location_command_stdout)
    ic(package_location)

    package_name_and_version = package.name
    ebuild_path = Path(os.fsdecode(package_location)) / Path(os.fsdecode(package_name_and_version + '.ebuild'))
    ic(ebuild_path)

    ebuild_clean_command = sh.sudo.ebuild(ebuild_path, 'clean', _fg=True,)
    ebuild_unpack_command = sh.sudo.ebuild(ebuild_path, 'unpack', _fg=True,)
    #ebuild_unpack_command_stdout = ebuild_unpack_command.stdout.splitlines()
    #ic(ebuild_unpack_command_stdout)
    ebuild_prepare_command = sh.sudo.ebuild(ebuild_path, 'prepare', _fg=True,)
    ebuild_configure_command = sh.sudo.ebuild(ebuild_path, 'configure', _fg=True,)
    work_dir = Path('/var/tmp/portage') / package / Path('work')
    ic(work_dir)
    sh.sudo.chmod('-R', 'a+rx', work_dir.parent, _fg=True)


@cli.command()
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def files_provided_by_package(ctx,
                              package: str,
                              verbose: int,
                              verbose_inf: bool,
                              ):
    tty, verbose = tv(ctx=ctx,
                      verbose=verbose,
                      verbose_inf=verbose_inf,
                      )
    #oet = {'_out': sys.stdout, '_err': sys.stderr, '_tee': not tty,}
    oe = {'_out': sys.stdout, '_err': sys.stderr,}

    qlist_command = sh.Command('qlist')
    qlist_command = qlist_command.bake('--exact', package)
    if tty:  # uug
        qlist_command = qlist_command(**oe, _tee=not tty, _tty_out=tty)
        return
    else:
        qlist_command = qlist_command(_tty_out=tty)  # could drop _tty_out, sh patch testing

    qlist_stdout_lines = qlist_command.stdout.splitlines()

    for line in qlist_stdout_lines:
        if verbose == inf:  # `verbose: int >= math inf` debug protocol works  #inf has always been a float... all `verbose: int` type annotations are wrong
            ic(line)
        output(line, tty=tty, verbose=verbose)


@click.command()
@click.argument("package", type=str, nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def emerge_keepwork(ctx,
                    package: str,
                    verbose: int,
                    verbose_inf: bool,
                    ):
    tty, verbose = tv(ctx=ctx,
                      verbose=verbose,
                      verbose_inf=verbose_inf,
                      )

    sh.emerge('--verbose', '--tree', '--usepkg=n', package, _out=sys.stdout, _err=sys.stderr, _env={"FEATURES": "keepwork"},)


@cli.command('install')
@click.argument("package", type=str, nargs=1)
@click.option('--force-use', is_flag=True)
@click.option('--upgrade-only', is_flag=True)
@click_add_options(click_global_options)
@click.pass_context
def _install_package(ctx,
                     package: str,
                     verbose: int,
                     verbose_inf: bool,
                     force_use: bool,
                     upgrade_only: bool,
                     ):
    tty, verbose = tv(ctx=ctx,
                      verbose=verbose,
                      verbose_inf=verbose_inf,
                      )

    if force_use:
        install_packages_force(packages=(package,), verbose=verbose, upgrade_only=upgrade_only)
    else:
        install_packages(packages=(package,), verbose=verbose,)
