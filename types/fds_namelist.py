"""!
BlenderFDS, Blender representations of a FDS namelist.
"""

import re, logging
from .fds_param import FDSParam

log = logging.getLogger(__name__)


class FDSNamelist:
    """!
    List of BFParam instances representing an FDS namelist.
    """

    ## max number of columns of formatted output
    MAXLEN = 80  # TODO to config

    def __init__(self, fds_label=None, fds_params=None, msgs=None) -> None:
        """!
        Class constructor.
        @param fds_label: namelist group label.
        @param fds_params: list of FDSParam and additional FDSNamelist instances.
        @param msgs: list of comment message strings.
        """
        ## namelist group label
        self.fds_label = fds_label
        ## list (single) of FDSParam and additional FDSNamelist,
        ## or list of list (multi) of FDSParam instances
        ## eg. (("ID=X1", "PBX=1"), ("ID=X2", "PBX=2"), ...)
        self.fds_params = fds_params and list(fds_params) or list()
        ## list of comment message strings
        self.msgs = msgs and list(msgs) or list()

    def __str__(self) -> str:
        try:
            return self.to_fds()
        except:
            return self.__repr__()

    def __repr__(self) -> str:
        items = ", ".join(f'{k}={v!r}' for k, v in self.__dict__.items())
        return f"<{self.__class__.__name__}({items})>"

    def __contains__(self, fds_label) -> bool:
        # self can be a list of lists (multi), but only when exporting
        # in that case this fails
        return fds_label in (fds_params.fds_label for fds_params in self.fds_params)

    def copy(self):  # shallow copy
        return FDSNamelist(fds_label=self.fds_label, fds_params=self.fds_params[:], msgs=self.msgs[:])

    def get_fds_param(self, fds_label, remove) -> FDSParam or None:
        """!
        Return and remove the first FDSParam instance in self.fds_params by its fds_label.
        @param fds_label: namelist parameter label.
        @return None or FDSParam.
        """
        # self.fds_params can be a list of lists (multi), but only when exporting
        # in that case this fails
        for fds_param in self.fds_params:
            if not fds_param:
                continue
            if fds_label and fds_param.fds_label != fds_label:
                continue
            if remove:
                self.fds_params.remove(fds_param)
            return fds_param

    def _classify_fds_param(self, p):
        match p:
            case None:
                return
            case FDSParam():
                self._invariant_ps.append(p)
                self.msgs.extend(p.msgs)
            case FDSNamelist():
                self._additional_ns.append(p)
                self.msgs.extend(p.msgs)
            case FDSMany():  # flatten many
                for pp in p:
                    self._classify_fds_param(pp)
                self.msgs.extend(p.msgs)
            case FDSMulti():  # get one multi
                if self._multi_ps:
                    raise Exception(f"One only FDSMulti allowed in: {self!r}")
                self._multi_ps = p
                self.msgs.extend(p.msgs)
            case _:
                raise ValueError(f"Unrecognized type of <{p!r}> in <{self!r}>")


    def to_fds(self, context=None) -> str:
        """!
        Return the FDS formatted string.
        @return FDS formatted string (eg. "&OBST ID='Test' /"), or a None.
        """
        # Classify params
        self._invariant_ps, self._additional_ns, self._multi_ps  = list(), list(), None
        for p in self.fds_params:
            self._classify_fds_param(p)
        # Treat invariant, many and multi parameters
        # nl = FDSParam, FDSParam, ...
        nls = list()  # list of nl
        if self._multi_ps:
            # Remove parameters in invariant_ps that exist in multi_ps (eg. ID, IJK or XB)
            multi_ps_fds_labels = [p.fds_label for p in self._multi_ps[0]]  # labels from multi_ps
            self._invariant_ps = [p for p in self._invariant_ps if p.fds_label not in multi_ps_fds_labels]
            # Add nl with one of multi_ps + invariant_ps
            for multi_p in self._multi_ps:
                nl = list()
                nl.extend(self._invariant_ps)  # first invariant params
                nl.extend(multi_p)  # then multi params
                nls.append(nl)
        else:
            nls.append(self._invariant_ps)
        # Prepare message lines
        lines = list(f"! {m}" for m in self.msgs if m)  # all messages
        # Treat additional namelists first
        lines.extend(n.to_fds(context) for n in self._additional_ns)
        # Prepare namelist lines
        if self.fds_label:
            for nl in nls:
                newline = False
                line = f"&{self.fds_label}"
                for p in nl:
                    if not p.fds_label:
                        continue
                    label = p.fds_label
                    vs = p._get_formatted_values()  # list of str
                    if not vs:  # no formatted values
                        if not newline and len(line) + 1 + len(label) <= self.MAXLEN:
                            # Parameter to the same line
                            newline = False
                            line += " " + label
                        else:
                            # Parameter to new line
                            lines.append(line)
                            line = "      " + label  # new line
                    else:  # available formatted values
                        v = ",".join(vs)  # values str
                        if (
                            not newline
                            and len(line) + 1 + len(label) + 1 + len(v) <= self.MAXLEN
                        ):
                            # Parameter to the same line
                            newline = False
                            line += " " + label + "=" + v
                        else:
                            # Parameter to new line
                            lines.append(line)
                            line = "      " + label + "="  # new line
                            if len(line) + len(v) <= self.MAXLEN:
                                # Formatted values do not need splitting
                                line += v
                            else:
                                # Formatted values need splitting
                                newline = True  # the following needs a new line
                                for v in vs:
                                    if len(line) + len(v) + 1 <= self.MAXLEN:
                                        line += v + ","
                                    else:
                                        lines.append(line)
                                        line = "        " + v + ","  # new line
                                line = line[:-1]  # remove last ","
                line += " /"
                lines.append(line)
        return "\n".join(lines)

    _RE_SCAN_PARAMS = re.compile(
        r"""
        ([A-Z][A-Z0-9_\(\):,]*?)  # label (group 0)
        [,\s\t]*                  # 0+ separators
        =                         # = sign
        [,\s\t]*                  # 0+ separators
        (                         # value (group 1)
            (?:'.*?'|".*?"|.+?)*?     # 1+ any char, protect str, not greedy
                (?=                       # end previous match when:
                    (?:                       # there is another label:
                        [,\s\t]+                  # 1+ separators
                        [A-Z][A-Z0-9_\(\):,]*?    # label
                        [,\s\t]*                  # 0+ separators
                        =                         # = sign
                    )
                |                         # or
                    $                         # it is end of line
                )
        )
        """,
        re.VERBOSE | re.DOTALL | re.IGNORECASE,
    )  # no MULTILINE, so that $ is the end of the file

    def from_fds(self, f90) -> None:
        """!
        Import from FDS formatted string of parameters, on error raise BFException.
        @param f90: FDS formatted string of parameters, eg. "ID='Test' PROP=2.34, 1.23, 3.44".
        """
        # Remove trailing spaces and newlines, then scan it
        f90 = " ".join(f90.strip().splitlines())
        for match in re.finditer(self._RE_SCAN_PARAMS, f90):
            label, f90_value = match.groups()
            fds_param = FDSParam(fds_label=label)
            fds_param.from_fds(f90=f90_value)
            self.fds_params.append(fds_param)

class FDSMulti(list):
    def __init__(self, *args, msgs=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.msgs = msgs or list()

class FDSMany(list):
    def __init__(self, *args, msgs=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.msgs = msgs or list()
