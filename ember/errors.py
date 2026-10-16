"""Diagnostics for every compiler phase, rendered with the offending source line."""


class EmberError(Exception):
    phase = "Error"

    def __init__(self, message, line=None, col=None, notes=()):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col
        self.notes = list(notes)

    def __str__(self):
        where = f" at {self.line}:{self.col}" if self.line is not None else ""
        return f"{self.phase}{where}: {self.message}"

    def render(self, source):
        out = [str(self)]
        lines = source.splitlines()
        if self.line is not None and 1 <= self.line <= len(lines):
            gutter = f"{self.line:>4} | "
            out.append(gutter + lines[self.line - 1])
            out.append(" " * (len(gutter) + self.col - 1) + "^")
        out.extend(f"  note: {n}" for n in self.notes)
        return "\n".join(out)


class SyntaxErr(EmberError):
    phase = "SyntaxError"


class TypeErr(EmberError):
    phase = "TypeError"


class RuntimeErr(EmberError):
    phase = "RuntimeError"


class Warn(EmberError):
    phase = "Warning"
