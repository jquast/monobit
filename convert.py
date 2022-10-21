#!/usr/bin/env python3
"""
Apply operation to bitmap font
(c) 2019--2022 Rob Hagemans, licence: https://opensource.org/licenses/MIT
"""

import sys
import logging
from types import SimpleNamespace as Namespace
from pathlib import Path

import monobit
from monobit.scripting import main, parse_subcommands, print_help, argrecord


operations = {
    'load': monobit.load,
    'save': monobit.save,
    'to': monobit.save,
    **monobit.operations
}

global_options = {
    'help': (bool, 'Print a help message and exit.'),
    'version': (bool, 'Show monobit version and exit.'),
    'debug': (bool, 'Enable debugging output.'),
}

usage = (
    f'usage: {Path(__file__).name} '
    + '[INFILE] [LOAD-OPTIONS] '
    + ' '.join(f'[--{_op}]' for _op in global_options)
    + ' [COMMAND [OPTION...]] ...'
    + ' [to [OUTFILE] [SAVE_OPTIONS]]'
)

def _get_context_help(rec):
    if rec.args:
        file = rec.args[0]
    else:
        file = rec.kwargs.get('infile', '')
    format = rec.kwargs.get('format', '')
    if rec.command == 'load':
        func = monobit.loaders.get_for_location(file, format=format)
    else:
        func = monobit.savers.get_for_location(file, format=format, do_open=False)
    return func.script_args

def help(command_args):
    """Print the usage help message."""
    context_help = {
        _rec.command: _get_context_help(_rec)
        for _rec in command_args
        if _rec.command in ('load', 'save', 'to')
    }
    print_help(command_args, usage, operations, global_options, context_help)

def version():
    """Print the version string."""
    print(f'monobit v{monobit.__version__}')


command_args, global_args = parse_subcommands(operations, global_options=global_options)
debug = 'debug' in global_args.kwargs


with main(debug):
    if 'help' in global_args.kwargs:
        help(command_args)

    elif 'version' in global_args.kwargs:
        version()

    else:
        # ensure first command is load
        if not command_args[0].command and (
                command_args[0].args or command_args[0].kwargs
                or len(command_args) == 1 or command_args[1].command != 'load'
            ):
            command_args[0].command = 'load'
            command_args[0].func = operations['load']
        # ensure last command is save
        if command_args[-1].command not in ('to', 'save'):
            command_args.append(argrecord(command='save', func=operations['save']))

        fonts = []
        for args in command_args:
            if not args.command:
                continue
            logging.debug('Executing command `%s`', args.command)
            operation = operations[args.command]
            if operation == monobit.load:
                fonts += operation(*args.args, **args.kwargs)
            elif operation == monobit.save:
                operation(fonts, *args.args, **args.kwargs)
            else:
                fonts = tuple(
                    operation(_font, *args.args, **args.kwargs)
                    for _font in fonts
                )

