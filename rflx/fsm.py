from typing import Dict, Iterable, List, Optional

import yaml
from pyparsing import Keyword, Token

from rflx.error import Location, RecordFluxError, Severity, Subsystem
from rflx.expression import FALSE, TRUE, Equal, Expr, Variable
from rflx.model import Base
from rflx.parser.grammar import boolean_literal, unqualified_identifier


class StateName(Base):
    def __init__(self, name: str, location: Location = None):
        self.__name = name
        self.location = location

    @property
    def name(self) -> str:
        return self.__name


class Transition(Base):
    def __init__(self, target: StateName, condition: Expr = TRUE):
        self.__target = target
        self.__condition = condition

    @property
    def target(self) -> StateName:
        return self.__target


class State(Base):
    def __init__(self, name: StateName, transitions: Optional[Iterable[Transition]] = None):
        self.__name = name
        self.__transitions = transitions or []

    @property
    def name(self) -> StateName:
        return self.__name

    @property
    def transitions(self) -> Iterable[Transition]:
        return self.__transitions or []


class StateMachine(Base):
    def __init__(
        self,
        name: str,
        initial: StateName,
        final: StateName,
        states: Iterable[State],
        location: Location = None,
    ):
        self.__name = name
        self.__initial = initial
        self.__final = final
        self.__states = states
        self.location = location
        self.error = RecordFluxError()

        if not states:
            self.error.append(
                "empty states", Subsystem.SESSION, Severity.ERROR, location,
            )
        self.__validate_state_existence()
        self.__validate_duplicate_states()
        self.__validate_state_reachability()
        self.error.propagate()

    def __validate_state_existence(self) -> None:
        state_names = [s.name for s in self.__states]
        if self.__initial not in state_names:
            self.error.append(
                f'initial state "{self.__initial.name}" does not exist in "{self.__name}"',
                Subsystem.SESSION,
                Severity.ERROR,
                self.__initial.location,
            )
        if self.__final not in state_names:
            self.error.append(
                f'final state "{self.__final.name}" does not exist in "{self.__name}"',
                Subsystem.SESSION,
                Severity.ERROR,
                self.__final.location,
            )
        for s in self.__states:
            for t in s.transitions:
                if t.target not in state_names:
                    self.error.append(
                        f'transition from state "{s.name.name}" to non-existent state'
                        f' "{t.target.name}" in "{self.__name}"',
                        Subsystem.SESSION,
                        Severity.ERROR,
                        t.target.location,
                    )

    def __validate_duplicate_states(self) -> None:
        state_names = [s.name for s in self.__states]
        seen: Dict[str, int] = {}
        duplicates: List[str] = []
        for n in [x.name for x in state_names]:
            if n not in seen:
                seen[n] = 1
            else:
                if seen[n] == 1:
                    duplicates.append(n)
                seen[n] += 1

        if duplicates:
            self.error.append(
                f'duplicate states: {", ".join(sorted(duplicates))}',
                Subsystem.SESSION,
                Severity.ERROR,
                self.location,
            )

    def __validate_state_reachability(self) -> None:
        inputs: Dict[str, List[str]] = {}
        for s in self.__states:
            for t in s.transitions:
                if t.target.name in inputs:
                    inputs[t.target.name].append(s.name.name)
                else:
                    inputs[t.target.name] = [s.name.name]
        unreachable = [
            s.name.name
            for s in self.__states
            if s.name != self.__initial and s.name.name not in inputs
        ]
        if unreachable:
            self.error.append(
                f'unreachable states {", ".join(unreachable)}',
                Subsystem.SESSION,
                Severity.ERROR,
                self.location,
            )

        detached = [
            s.name.name for s in self.__states if s.name != self.__final and not s.transitions
        ]
        if detached:
            self.error.append(
                f'detached states {", ".join(detached)}',
                Subsystem.SESSION,
                Severity.ERROR,
                self.location,
            )


class FSM:
    def __init__(self) -> None:
        self.__fsms: List[StateMachine] = []
        self.error = RecordFluxError()

    @classmethod
    def logical_equation(cls) -> Token:
        result = unqualified_identifier() + Keyword("=") + boolean_literal()
        return result.setParseAction(
            lambda t: Equal(Variable(t[0]), TRUE if t[2] == "True" else FALSE)
        )

    def __parse(self, name: str, doc: Dict) -> None:
        if "initial" not in doc:
            self.error.append(
                f'missing initial state in "{name}"', Subsystem.SESSION, Severity.ERROR, None,
            )
        if "final" not in doc:
            self.error.append(
                f'missing final state in "{name}"', Subsystem.SESSION, Severity.ERROR, None,
            )
        if "states" not in doc:
            self.error.append(
                f'missing states section in "{name}"', Subsystem.SESSION, Severity.ERROR, None,
            )

        self.error.propagate()

        states: List[State] = []
        for s in doc["states"]:
            transitions: List[Transition] = []
            if "transitions" in s:
                for index, t in enumerate(s["transitions"]):
                    if "condition" in t:
                        try:
                            condition = FSM.logical_equation().parseString(t["condition"])[0]
                        except RecordFluxError as e:
                            self.error.extend(e)
                            sname = s["name"]
                            tname = t["target"]
                            self.error.append(
                                f'invalid condition {index} from state "{sname}" to "{tname}"',
                                Subsystem.SESSION,
                                Severity.ERROR,
                                None,
                            )
                            continue
                    else:
                        condition = TRUE
                    transitions.append(
                        Transition(target=StateName(t["target"]), condition=condition)
                    )
            states.append(State(name=StateName(s["name"]), transitions=transitions))

        self.error.propagate()

        fsm = StateMachine(
            name=name,
            initial=StateName(doc["initial"]),
            final=StateName(doc["final"]),
            states=states,
        )
        self.error.extend(fsm.error)
        self.__fsms.append(fsm)
        self.error.propagate()

    def parse(self, name: str, filename: str) -> None:
        with open(filename, "r") as data:
            self.__parse(name, yaml.safe_load(data))

    def parse_string(self, name: str, string: str) -> None:
        self.__parse(name, yaml.safe_load(string))

    @property
    def fsms(self) -> List[StateMachine]:
        return self.__fsms
