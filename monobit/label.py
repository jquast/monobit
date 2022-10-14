"""
monobit.label - yaff representation of labels

(c) 2020--2022 Rob Hagemans
licence: https://opensource.org/licenses/MIT
"""

from string import ascii_letters
from binascii import hexlify

from .binary import ceildiv, int_to_bytes
from .scripting import any_int


def is_enclosed(from_str, char):
    """Check if a char occurs on both sides of a string."""
    if not char:
        return True
    return len(from_str) >= 2*len(char) and from_str.startswith(char) and from_str.endswith(char)

def strip_matching(from_str, char, allow_no_match=True):
    """Strip a char from either side of the string if it occurs on both."""
    if not char:
        return from_str
    if is_enclosed(from_str, char):
        clen = len(char)
        return from_str[clen:-clen]
    elif not allow_no_match:
        raise ValueError(f'No matching delimiters `{char}` found in string `{from_str}`.')
    return from_str


##############################################################################
# label types

class Label:
    """Label."""

    def __repr__(self):
        """Represent label."""
        return f"{type(self).__name__}({super().__repr__()})"


def label(value):
    """Convert to codepoint/unicode/tag label from yaff file."""
    if isinstance(value, Label):
        return value
    if not isinstance(value, str):
        # only Codepoint can have non-str argument
        return codepoint(value)
    # remove leading and trailing whitespace
    value = value.strip()
    if not value:
        return char()
    # protect commas, pluses etc. if enclosed
    if is_enclosed(value, '"'):
        # strip matching double quotes - this allows to set a label starting with a digit by quoting it
        value = strip_matching(value, '"')
        return Tag(value)
    if is_enclosed(value, "'"):
        value = strip_matching(value, "'")
        return char(value)
    # codepoints start with an ascii digit
    try:
        return codepoint(value)
    except ValueError:
        pass
    # length-one -> always a character
    if len(value) == 1:
        return char(value)
    # non-ascii first char -> always a character
    # note that this includes non-printables such as controls but these should not be used.
    if ord(value[0]) >= 0x80:
        return char(value)
    # deal with other options such as single-quoted, u+codepoint and sequences
    try:
        elements = value.split(',')
        return Char(''.join(
            _convert_char_element(_elem)
            for _elem in elements if _elem
        ))
    except ValueError:
        pass
    return Tag(value)

def _convert_char_element(element):
    """Convert character label element to char if possible."""
    # string delimited by single quotes denotes a character or sequence
    try:
        element = strip_matching(element, "'", allow_no_match=False)
    except ValueError:
        pass
    else:
        return element
    # not a delimited char
    element = element.lower()
    if not element.startswith('u+'):
        raise ValueError(element)
    # convert to sequence of chars
    # this will raise ValueError if not possible
    cp_ord = int(element.strip()[2:], 16)
    return chr(cp_ord)


label_from_yaff = label
label_to_yaff = str


##############################################################################
# character labels

class Char(Label, str):
    """Character label."""

    def __str__(self):
        """Convert to unicode label str for yaff."""
        return ', '.join(
            f'u+{ord(_uc):04x}'
            for _uc in self
        )

def char(value=''):
    """Convert char or char sequence to char label."""
    if isinstance(value, Char):
        return value
    if value is None:
        value = ''
    if isinstance(value, str):
        # strip matching single quotes - if the character label should be literally '', use ''''.
        return Char(value)
    raise ValueError(
        f'Cannot convert value {repr(value)} of type {type(value)} to character label.'
    )



##############################################################################
# codepoints


class Codepoint(Label, bytes):
    """Codepoint label."""

    def __str__(self):
        """Convert codepoint label to str."""
        return '0x' + hexlify(self).decode('ascii')


def codepoint(value=b''):
    """Convert to codepoint label if possible."""
    if isinstance(value, Codepoint):
        return value
    if value is None:
        value = b''
    if isinstance(value, bytes):
        return _strip_codepoint(value)
    if isinstance(value, int):
        return _strip_codepoint(int_to_bytes(value))
    if isinstance(value, str):
        # handle composite labels
        # codepoint sequences (MBCS) "0xf5,0x02" etc.
        value = value.split(',')
    # deal with other iterables, e.g. bytes, tuple
    try:
        value = b''.join(int_to_bytes(any_int(_i)) for _i in value)
    except (TypeError, OverflowError):
        raise ValueError(
            f'Cannot convert value {repr(value)} of type {type(value)} to codepoint label.'
        ) from None
    return _strip_codepoint(value)

def _strip_codepoint(value):
    if len(value) > 1:
        value = value.lstrip(b'\0')
    return Codepoint(value)



def codepoint_to_str(value):
    """Convert codepoint label to str."""
    return str(Codepoint(value))

def char_to_yaff(value):
    """Convert codepoint label to str."""
    return str(Char(value))

##############################################################################
# tags

class Tag(Label):
    """Tag label."""

    def __init__(self, value=''):
        """Construct tag object."""
        if isinstance(value, Tag):
            self._value = value.value
            return
        if value is None:
            value = ''
        if not isinstance(value, str):
            raise ValueError(
                f'Cannot convert value {repr(value)} of type {type(value)} to tag.'
            )
        self._value = value


    def __repr__(self):
        """Represent label."""
        return f"{type(self).__name__}({repr(self._value)})"

    def __str__(self):
        """Convert tag to str."""
        # quote otherwise ambiguous/illegal tags
        if (
                len(self._value) < 2
                or ord(self._value[0]) >= 0x80
                or '+' in self._value
                or not (self._value[0] in ascii_letters)
                or (self._value.startswith('"') and self._value.endswith('"'))
                or (self._value.startswith("'") and self._value.endswith("'"))
            ):
            return f'"{self._value}"'
        return self._value

    def __hash__(self):
        """Allow use as dictionary key."""
        # make sure tag and Char don't collide
        return hash((type(self), self._value))

    def __eq__(self, other):
        return type(self) == type(other) and self._value == other.value

    def __bool__(self):
        return bool(self._value)

    def __len__(self):
        return len(self._value)

    @property
    def value(self):
        """Value of the codepoint in base type."""
        # pylint: disable=no-member
        return self._value








