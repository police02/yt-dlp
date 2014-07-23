from __future__ import unicode_literals

import re

from .utils import (
    ExtractorError,
)


class JSInterpreter(object):
    def __init__(self, code):
        self.code = code
        self._functions = {}
        self._objects = {}

    def interpret_statement(self, stmt, local_vars, allow_recursion=20):
        if allow_recursion < 0:
            raise ExtractorError('Recursion limit reached')

        if stmt.startswith('var '):
            stmt = stmt[len('var '):]
        ass_m = re.match(r'^(?P<out>[a-z]+)(?:\[(?P<index>[^\]]+)\])?' +
                         r'=(?P<expr>.*)$', stmt)
        if ass_m:
            if ass_m.groupdict().get('index'):
                def assign(val):
                    lvar = local_vars[ass_m.group('out')]
                    idx = self.interpret_expression(
                        ass_m.group('index'), local_vars, allow_recursion)
                    assert isinstance(idx, int)
                    lvar[idx] = val
                    return val
                expr = ass_m.group('expr')
            else:
                def assign(val):
                    local_vars[ass_m.group('out')] = val
                    return val
                expr = ass_m.group('expr')
        elif stmt.startswith('return '):
            assign = lambda v: v
            expr = stmt[len('return '):]
        else:
            raise ExtractorError(
                'Cannot determine left side of statement in %r' % stmt)

        v = self.interpret_expression(expr, local_vars, allow_recursion)
        return assign(v)

    def interpret_expression(self, expr, local_vars, allow_recursion):
        if expr.isdigit():
            return int(expr)

        if expr.isalpha():
            return local_vars[expr]

        m = re.match(r'^(?P<in>[a-z]+)\.(?P<member>.*)$', expr)
        if m:
            member = m.group('member')
            variable = m.group('in')

            if variable not in local_vars:
                if variable not in self._objects:
                    self._objects[variable] = self.extract_object(variable)
                obj = self._objects[variable]
                key, args = member.split('(', 1)
                args = args.strip(')')
                argvals = [int(v) if v.isdigit() else local_vars[v]
                           for v in args.split(',')]
                return obj[key](argvals)

            val = local_vars[variable]
            if member == 'split("")':
                return list(val)
            if member == 'join("")':
                return ''.join(val)
            if member == 'length':
                return len(val)
            if member == 'reverse()':
                return val[::-1]
            slice_m = re.match(r'slice\((?P<idx>.*)\)', member)
            if slice_m:
                idx = self.interpret_expression(
                    slice_m.group('idx'), local_vars, allow_recursion - 1)
                return val[idx:]

        m = re.match(
            r'^(?P<in>[a-z]+)\[(?P<idx>.+)\]$', expr)
        if m:
            val = local_vars[m.group('in')]
            idx = self.interpret_expression(
                m.group('idx'), local_vars, allow_recursion - 1)
            return val[idx]

        m = re.match(r'^(?P<a>.+?)(?P<op>[%])(?P<b>.+?)$', expr)
        if m:
            a = self.interpret_expression(
                m.group('a'), local_vars, allow_recursion)
            b = self.interpret_expression(
                m.group('b'), local_vars, allow_recursion)
            return a % b

        m = re.match(
            r'^(?P<func>[a-zA-Z$]+)\((?P<args>[a-z0-9,]+)\)$', expr)
        if m:
            fname = m.group('func')
            if fname not in self._functions:
                self._functions[fname] = self.extract_function(fname)
            argvals = [int(v) if v.isdigit() else local_vars[v]
                       for v in m.group('args').split(',')]
            return self._functions[fname](argvals)
        raise ExtractorError('Unsupported JS expression %r' % expr)

    def extract_object(self, objname):
        obj = {}
        obj_m = re.search(
            (r'(?:var\s+)?%s\s*=\s*\{' % re.escape(objname)) +
            r'\s*(?P<fields>([a-zA-Z$0-9]+\s*:\s*function\(.*?\)\s*\{.*?\})*)' +
            r'\}\s*;',
            self.code)
        fields = obj_m.group('fields')
        # Currently, it only supports function definitions
        fields_m = re.finditer(
            r'(?P<key>[a-zA-Z$0-9]+)\s*:\s*function'
            r'\((?P<args>[a-z,]+)\){(?P<code>[^}]+)}',
            fields)
        for f in fields_m:
            argnames = f.group('args').split(',')
            obj[f.group('key')] = self.build_function(argnames, f.group('code'))

        return obj

    def extract_function(self, funcname):
        func_m = re.search(
            (r'(?:function %s|[{;]%s\s*=\s*function)' % (
                re.escape(funcname), re.escape(funcname))) +
            r'\((?P<args>[a-z,]+)\){(?P<code>[^}]+)}',
            self.code)
        if func_m is None:
            raise ExtractorError('Could not find JS function %r' % funcname)
        argnames = func_m.group('args').split(',')

        return self.build_function(argnames, func_m.group('code'))

    def build_function(self, argnames, code):
        def resf(args):
            local_vars = dict(zip(argnames, args))
            for stmt in code.split(';'):
                res = self.interpret_statement(stmt, local_vars)
            return res
        return resf
