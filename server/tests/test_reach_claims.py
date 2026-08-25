"""A reach claim names a set; a test walks the set — JOB #3766, property 4.

A docstring that says which callers a function serves is a self-description
with a checkable subject, and this board has one instance that stayed false
for the whole life of the code: `_held` claimed "for `state` and `jobs`
alike" while `jobs` never called it. That was found in 2026 (#2092/#2095,
JOB #2207), written up in a comment inside `jobs`, and the docstring itself
was never corrected — so the claim a reader meets FIRST stayed wrong while
its refutation lived 1,700 lines away in the function that disproves it.

The general lesson is the one #3762 states: nothing checked a description
against its subject, and every instance was caught by something else
failing. This file is the check for the reach-claim class.

WHY AST AND NOT A GREP. The caller set is derived by parsing the module
and walking the tree, so it is read out of the subject rather than
carried here as a literal (#2595). A grep for `_held(` would also match
the definition, a mention inside a string, and the word inside a comment
— which is how a reach check ends up confirming itself.
"""

from __future__ import annotations

import ast
import pathlib

REDUCTIONS = pathlib.Path(__file__).resolve().parents[1] / "korax" / "reductions.py"


def _callers_of(source: str, target: str) -> set[str]:
    """Names of the module-level functions containing a call to `target`.

    The definition itself is not a call and does not count; a recursive
    call would name the function itself, which is the honest answer.
    """
    tree = ast.parse(source)
    found: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if isinstance(func, ast.Name) and func.id == target and self.stack:
                found.add(self.stack[0])
            self.generic_visit(node)

    Visitor().visit(tree)
    return found


def test_held_is_reached_from_exactly_the_callers_its_docstring_names() -> None:
    """`_held`'s narrowed claim is "`state`'s implementation. ONE caller."

    If `jobs` — or anything else — starts calling it, that sentence is
    false again and this reddens at the commit that makes it so, which is
    the whole difference between a description and a guarded description.
    """
    callers = _callers_of(REDUCTIONS.read_text(), "_held")
    assert callers == {"state"}, (
        f"`_held`'s docstring claims `state` alone; the code is called from "
        f"{sorted(callers)}. Either narrow the docstring to match or, if the "
        f"new caller is intended, say so there — a reach claim names a set "
        f"and this test walks it."
    )


def test_the_docstring_does_not_reclaim_the_reach_it_lost() -> None:
    """The specific false sentence, pinned by its text.

    Narrowing prose is not durable on its own — the next author rewriting
    this docstring has no signal that one phrasing was measured false.
    This is that signal."""
    source = REDUCTIONS.read_text()
    start = source.index("def _held(")
    doc = source[start : source.index('"""', source.index('"""', start) + 3)]
    assert "for `state` and `jobs`\n    alike" not in doc, (
        "`_held`'s docstring has re-acquired the reach claim measured false "
        "at JOB #2207 and again at #3766: `jobs` does not call this function"
    )


def test_the_x2_invariant_still_has_a_guard_somewhere() -> None:
    """`_held`'s docstring now points at a test BY NAME as the place the
    X2 invariant actually lives. A pointer to a test that has been renamed
    or deleted is worse than no pointer — it reads as reassurance.

    So the named test must exist. This does not run it; it asserts the
    citation resolves."""
    named = "test_state_and_jobs_agree_at_every_offset"
    fixture07 = REDUCTIONS.parents[1] / "tests" / "test_fixture07.py"
    assert named in fixture07.read_text(), (
        f"`_held`'s docstring cites `{named}` as where the X2 invariant is "
        f"held; it is not in {fixture07.name}. Either the guard moved and "
        f"the citation must follow it, or the guard is gone and the "
        f"docstring is promising a check that no longer exists."
    )
