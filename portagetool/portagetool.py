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

import os
import sys
import time
from signal import SIG_DFL
from signal import SIGPIPE
from signal import signal

import click
import sh

signal(SIGPIPE, SIG_DFL)
from pathlib import Path
from typing import ByteString
from typing import Generator
from typing import Iterable
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import Union

from asserttool import eprint
from asserttool import ic
from asserttool import nevd
from asserttool import validate_slice
from asserttool import verify
from enumerate_input import enumerate_input
from pathtool import write_line_to_file
from retry_on_exception import retry_on_exception


def get_use_flags_for_package(package: str,
                              *,
                              verbose: bool = False,
                              debug: bool = False,
                              ):

    result = sh.cat(sh.equery('u', package, _piped=True))
    result = result.strip()
    if verbose:
        ic(result)
    result = [r[1:] for r in result.split('\n')]

    return result


def install_package(package: str,
                    *,
                    verbose: bool = False,
                    debug: bool = False,
                    ):

    ic(package)
    sh.emerge('--with-bdeps=y', '-pv', '--tree', '--usepkg=n', '-u', '--ask', 'n', '-n', package, _out=sys.stdout, _err=sys.stderr)
    #for line in sh.emerge('--with-bdeps=y', '-pv', '--tree', '--usepkg=n', '-u', '--ask', 'n', '-n', package, _piped=True):
    #    eprint(line, end='')
    for line in sh.emerge('--with-bdeps=y', '-v', '--tree', '--usepkg=n', '-u', '--ask', 'n', '-n', package, _piped=True):
        eprint(line, end='')


def install_package_force(package: str,
                          *,
                          verbose: bool = False,
                          debug: bool = False,
                          ):

    _env = {'CONFIG_PROTECT': '-*'}
    ic(package)

    #for line in sh.emerge('--with-bdeps=y', '-pv', '--tree', '--usepkg=n', '-u', '--ask', 'n', '-n', package, _piped=True):
    #    eprint(line, end='')

    #for line in sh.emerge('--with-bdeps=y', '-v', '--tree', '--usepkg=n', '-u', '--ask', 'n', '-n', package, _piped=True):
    #    eprint(line, end='')

    for line in sh.emerge('--with-bdeps=y', '-pv',     '--tree', '--usepkg=n', '-u', '--ask', 'n', '--autounmask', '--autounmask-write', '-n', package, _env=_env, _piped=True):
        eprint(line, end='')

    #sh.emerge('--with-bdeps=y', '--quiet', '--tree', '--usepkg=n', '-u', '--ask', 'n', '--autounmask', '--autounmask-write', '-n', package, _env=_env)
    for line in sh.emerge('--with-bdeps=y', '--quiet', '--tree', '--usepkg=n', '-u', '--ask', 'n', '--autounmask', '--autounmask-write', '-n', package, _env=_env, _piped=True):
        eprint(line, end='')



def add_accept_keyword(package: str,
                       *,
                       verbose: bool = False,
                       debug: bool = False,
                       ):

    line = "={package} **".format(package=package)
    if verbose:
        ic(line)
    write_line_to_file(path=Path('/etc/portage/package.accept_keywords'),
                       line=line + '\n',
                       unique=True,
                       verbose=verbose,
                       debug=debug,)


@click.group()
@click.option('--verbose', is_flag=True)
@click.option('--debug', is_flag=True)
@click.pass_context
def cli(ctx,
        verbose: bool,
        debug: bool,
        ):

    null, end, verbose, debug = nevd(ctx=ctx,
                                     printn=False,
                                     ipython=False,
                                     verbose=verbose,
                                     debug=debug,)


@cli.command()
@click.argument("package", type=str, nargs=1)
@click.option('--verbose', is_flag=True)
@click.option('--debug', is_flag=True)
@click.pass_context
def use_flags_for_package(ctx,
                          package: str,
                          verbose: bool,
                          debug: bool,
                          ):

    null, end, verbose, debug = nevd(ctx=ctx,
                                     printn=False,
                                     ipython=False,
                                     verbose=verbose,
                                     debug=debug,)

    flags = get_use_flags_for_package(package=package, verbose=verbose, debug=debug)
    for flag in flags:
        sys.stdout.buffer.write(flag.encode('utf8') + end)


