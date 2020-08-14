from typing import Dict, List, Sequence

from rflx.declaration import (
    ChannelDeclaration,
    Declaration,
    PrivateDeclaration,
    RenamingDeclaration,
    SubprogramDeclaration,
    VariableDeclaration,
)
from rflx.error import Location, RecordFluxError, Severity, Subsystem
from rflx.expression import TRUE, Expr
from rflx.identifier import ID, StrID
from rflx.model import Base
from rflx.statement import Statement


class Transition(Base):
    def __init__(
        self,
        target: StrID,
        condition: Expr = TRUE,
        description: str = None,
        location: Location = None,
    ):
        self.target = ID(target)
        self.condition = condition
        self.location = location
        self.description = description

    def validate(self, declarations: Dict[ID, Declaration]) -> None:
        self.condition.simplified().validate(declarations)


class State(Base):
    def __init__(
        self,
        name: StrID,
        transitions: Sequence[Transition] = None,
        actions: Sequence[Statement] = None,
        declarations: Sequence[Declaration] = None,
        location: Location = None,
    ):
        self.__name = ID(name)
        self.__transitions = transitions or []
        self.__actions = actions or []
        self.declarations = {d.identifier: d for d in declarations} if declarations else {}
        self.location = location

    @property
    def name(self) -> ID:
        return self.__name

    @property
    def transitions(self) -> Sequence[Transition]:
        return self.__transitions or []

    @property
    def actions(self) -> Sequence[Statement]:
        return self.__actions


class Session(Base):
    # pylint: disable=too-many-arguments, too-many-instance-attributes
    def __init__(
        self,
        name: StrID,
        initial: StrID,
        final: StrID,
        states: Sequence[State],
        declarations: Sequence[Declaration],
        parameters: Sequence[Declaration] = None,
        location: Location = None,
    ):
        self.name = ID(name)
        self.initial = ID(initial)
        self.final = ID(final)
        self.states = states
        self.declarations = {d.identifier: d for d in declarations}
        self.parameters = {p.identifier: p for p in parameters} if parameters else {}
        self.location = location
        self.error = RecordFluxError()

        if not states:
            self.error.append(
                "empty states", Subsystem.MODEL, Severity.ERROR, location,
            )
        self.__validate_state_existence()
        self.__validate_duplicate_states()
        self.__validate_state_reachability()
        self.__validate_conditions()
        self.__validate_actions()
        self.__validate_declarations()
        self.error.propagate()

    def __validate_conditions(self) -> None:
        for s in self.states:
            declarations = s.declarations
            for t in s.transitions:
                try:
                    t.validate({**self.parameters, **self.declarations, **declarations})
                except RecordFluxError as e:
                    self.error.extend(e)

    def __validate_actions(self) -> None:
        for s in self.states:
            declarations = s.declarations
            for index, a in enumerate(s.actions):
                try:
                    a.validate({**self.parameters, **self.declarations, **declarations})
                except RecordFluxError as e:
                    self.error.append(
                        f"invalid action {index} of state {s.name}",
                        Subsystem.MODEL,
                        Severity.ERROR,
                        a.location,
                    )
                    self.error.extend(e)

    def __validate_state_existence(self) -> None:
        state_names = [s.name for s in self.states]
        if self.initial not in state_names:
            self.error.append(
                f'initial state "{self.initial}" does not exist in "{self.name}"',
                Subsystem.MODEL,
                Severity.ERROR,
                self.initial.location,
            )
        if self.final not in state_names:
            self.error.append(
                f'final state "{self.final}" does not exist in "{self.name}"',
                Subsystem.MODEL,
                Severity.ERROR,
                self.final.location,
            )
        for s in self.states:
            for t in s.transitions:
                if t.target not in state_names:
                    self.error.append(
                        f'transition from state "{s.name}" to non-existent state'
                        f' "{t.target}" in "{self.name}"',
                        Subsystem.MODEL,
                        Severity.ERROR,
                        t.target.location,
                    )

    def __validate_duplicate_states(self) -> None:
        state_names = [s.name for s in self.states]
        seen: Dict[ID, int] = {}
        duplicates: List[ID] = []
        for n in state_names:
            if n not in seen:
                seen[n] = 1
            else:
                duplicates.append(n.name)
                seen[n] += 1

        if duplicates:
            self.error.append(
                f'duplicate states: {", ".join(map(str, sorted(duplicates)))}',
                Subsystem.MODEL,
                Severity.ERROR,
                self.location,
            )

    def __validate_state_reachability(self) -> None:
        inputs: Dict[ID, List[ID]] = {}
        for s in self.states:
            for t in s.transitions:
                if t.target in inputs:
                    inputs[t.target].append(s.name)
                else:
                    inputs[t.target] = [s.name]
        unreachable = [
            str(s.name) for s in self.states if s.name != self.initial and s.name not in inputs
        ]
        if unreachable:
            self.error.append(
                f'unreachable states {", ".join(unreachable)}',
                Subsystem.MODEL,
                Severity.ERROR,
                self.location,
            )

        detached = [str(s.name) for s in self.states if s.name != self.final and not s.transitions]
        if detached:
            self.error.append(
                f'detached states {", ".join(detached)}',
                Subsystem.MODEL,
                Severity.ERROR,
                self.location,
            )

    @staticmethod
    def __entity_name(decl: Declaration) -> str:
        if isinstance(decl, SubprogramDeclaration):
            return "subprogram"
        if isinstance(decl, VariableDeclaration):
            return "variable"
        if isinstance(decl, RenamingDeclaration):
            return "renames"
        if isinstance(decl, ChannelDeclaration):
            return "channel"
        if isinstance(decl, PrivateDeclaration):
            return "private"
        assert False, f"unsupported entity {type(decl).__name__}"

    def __validate_declarations(self) -> None:
        for s in self.states:
            for k, d in s.declarations.items():
                if k in self.declarations:
                    self.error.append(
                        f'local variable "{k}" shadows global declaration'
                        f" in state {s.name.name}",
                        Subsystem.MODEL,
                        Severity.ERROR,
                        self.location,
                    )
                if not s.declarations[k].is_referenced:
                    self.error.append(
                        f'unused local variable "{k}" in state {s.name.name}',
                        Subsystem.MODEL,
                        Severity.ERROR,
                        self.location,
                    )
                d.validate({**self.parameters, **self.declarations})
        for k, d in self.declarations.items():
            if str(k).upper() in ["READ", "WRITE", "CALL", "DATA_AVAILABLE", "APPEND", "EXTEND"]:
                self.error.append(
                    f'{self.__entity_name(d)} declaration shadows builtin subprogram "{k}"',
                    Subsystem.MODEL,
                    Severity.ERROR,
                    self.location,
                )
            try:
                d.validate({**self.parameters, **self.declarations})
            except RecordFluxError as e:
                self.error.extend(e)
        for k, d in self.declarations.items():
            # ISSUE: Componolit/RecordFlux#397
            if isinstance(d, PrivateDeclaration):
                continue
            if not d.is_referenced:
                self.error.append(
                    f'unused {self.__entity_name(d)} "{k}"',
                    Subsystem.MODEL,
                    Severity.ERROR,
                    self.location,
                )
