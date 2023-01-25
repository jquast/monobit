"""
monobit.formats.os2.lx - read OS/2 LX containers

(c) 2023 Rob Hagemans
licence: https://opensource.org/licenses/MIT


this is mostly ported code from gpifont.c and os2res.h
- http://www.altsan.org/programming/os2font_src.zip
- https://github.com/altsan/os2-gpi-font-tools

notice for gpifont.c and os2res.h:
>
>  (C) 2012 Alexander Taylor
>  This code is placed in the public domain.
>
"""

import logging

from ...streams import FileFormatError
from ...struct import little_endian as le

from .gpifont import OS2FONTDIRENTRY, OS2FONTDIRECTORY
from .ne import read_os2_ne


# from os2res.h

# 0x5A4D "MZ": DOS/old-style executable header
MAGIC_MZ = b'MZ'
# 0x454E "NE": 16-bit OS/2 executable header
MAGIC_NE = b'NE'
# 0x584C "LX": 32-bit OS/2 executable header
MAGIC_LX = b'LX'

# Location of the 'real' exe header offset
EH_OFFSET_ADDRESS = 0x3C

# OS/2 resource types that we're interested in.
OS2RES_FONTDIR = 6
OS2RES_FONTFACE = 7

# Values of interest for flags field of LXOPMENTRY (LX object page map entry).
# Normal unpacked data
OP32_VALID = 0x0000
# Data in EXEPACK1 format
OP32_ITERDATA = 0x0001
# Data in EXEPACK2 format
OP32_ITERDATA2 = 0x0005


# based on ReadOS2FontResource from gpifont.c
def read_os2_font(instream):
    """Read an OS/2 .FON file."""
    magic = instream.read(2)
    if magic == MAGIC_MZ:
        # Locate the new-type executable header
        instream.seek(EH_OFFSET_ADDRESS)
        addr = int(le.uint32.read_from(instream))
        # Read the 2-byte magic number from this address
        instream.seek(addr)
        magic = instream.read(2)
        # Now back up to the start of the new-type header again
        instream.seek(addr)
    elif magic in (MAGIC_LX, MAGIC_NE):
        # No stub header, just start at the beginning of the file
        addr = 0;
        instream.seek(addr)
    else:
        # Not a compiled (exe) font module
        raise FileFormatError('Not an OS/2 FON file.')
    # Identify the executable type and parse the resource data accordingly
    if magic == MAGIC_LX:
        return _read_lx(instream)
    else:
        return read_os2_ne(instream)


# 32-bit EXE header
LXHEADER = le.Struct(
    # 0x4C58 ("LX")
    magic='2s',
    # various unnecessary fields
    unused1=le.uint8.array(42),
    # page alignment shift
    pageshift='uint32',
    # various unnecessary fields
    unused2=le.uint8.array(8),
    # loader section size
    ldrsize='uint32',
    # loader section checksum
    ldrsum='uint32',
    # offset to object table
    obj_tbl='uint32',
    # various unnecessary fields
    unused3=le.uint8.array(4),
    # offset to object page map
    objmap='uint32',
    # various unnecessary fields
    unused4=le.uint8.array(4),
    # offset to resource table
    res_tbl='uint32',
    # number of resource entries
    cres='uint32',
    # offset to resident-names table
    rnam_tbl='uint32',
    # various unnecessary fields
    unused5=le.uint8.array(36),
    # offset to data pages
    datapage='uint32',
    # 64 bytes of various unnecessary fields follow
)

# Resource table entry
LXRTENTRY = le.Struct(
    type='uint16',
    name='uint16',
    cb='uint32',
    obj='uint16',
    offset='uint32',
)


def _read_lx(instream):
    """Read font resources from an LX container."""
    resources = []
    ulAddr = instream.tell()
    lx_hd = LXHEADER.read_from(instream)
    # Make sure the file actually contains resources...
    if not lx_hd.cres:
        raise FileFormatError('No resources found in LX file.')
    # Now look for font resources
    cb_rte = LXRTENTRY.size
    ulResID = ()
    for i in range(lx_hd.cres):
        cbInc = cb_rte * i
        instream.seek(ulAddr + lx_hd.res_tbl + cbInc)
        lx_rte = LXRTENTRY.read_from(instream)
        logging.debug(
            'Found resource of type %d with id %d',
            lx_rte.type, lx_rte.name
        )
        # don't insist on the type being 7 if the id matches the font directory
        if (
                lx_rte.type not in (OS2RES_FONTFACE, OS2RES_FONTDIR)
                and lx_rte.name not in ulResID
            ):
            continue
        # This is either our target font, or else a font directory
        pBuf = _lx_extract_resource(instream, lx_hd, lx_rte, ulAddr)
        if lx_rte.type == OS2RES_FONTDIR:
            logging.debug('Parsing font directory %d', lx_rte.name)
            # If a font directory exists we use that to find the face's
            # resource ID, as in this case it is not guaranteed to have
            # a type of OS2RES_FONTFACE (7).
            pFD = OS2FONTDIRECTORY.from_bytes(pBuf, lx_rte.offset)
            ulFaceCount = pFD.usnFonts
            fntEntry = OS2FONTDIRENTRY.array(ulFaceCount).from_bytes(
                pBuf, lx_rte.offset + OS2FONTDIRECTORY.size
            )
            # Set ulResID to the ID of the requested font number, then
            # continue scanning the resource table.
            ulResID = tuple(_fe.usIndex for _fe in fntEntry)
        else:
            logging.debug('Parsing font resource %d', lx_rte.name)
            # pBuf contains our font, so parse it.
            resources.append(pBuf)
    return resources


# Object table entry
LXOTENTRY = le.Struct(
    size='uint32',
    base='uint32',
    flags='uint32',
    pagemap='uint32',
    mapsize='uint32',
    reserved='uint32',
)

# Object page-map entry
LXOPMENTRY = le.Struct(
    dataoffset='uint32',
    size='uint16',
    flags='uint16',
)

def _lx_extract_resource(instream, lx_hd, lx_rte, ulBase):
    """
    Extracts a binary resource from an LX-format (32-bit OS/2) module.  The
    function takes a pointer to a buffer which will receive the extracted
    data of the object containing the resource.  It is up to the caller to
    locate the actual resource data within this buffer (this should be
    lx_rte.offset bytes from the start of the buffer).  The buffer is
    allocated by this function on successful return, and must be freed once
    no longer needed.

    This routine is based on information made available by Martin Lafaix,
    Veit Kannegieser and Max Alekseyev.

    ARGUMENTS:
      FILE      *pf      : Pointer to the open file.                      (I)
      LXHEADER   lx_hd   : LX-format executable header                    (I)
      LXRTENTRY  lx_rte  : Resource-table entry of the requested resource (I)
      ULONG      ulBase  : File offset of the LX-format header            (I)
    """
    cb_obj = LXOTENTRY.size
    cb_pme = LXOPMENTRY.size
    # Locate & read the object table entry for this resource
    instream.seek(ulBase + lx_hd.obj_tbl + cb_obj * (lx_rte.obj-1))
    lx_obj = LXOTENTRY.read_from(instream)
    # Locate & read the object page table entries for this object
    cbData = 0
    # - go to the first indicated entry in the pagemap
    instream.seek(ulBase + lx_hd.objmap + cb_pme * (lx_obj.pagemap-1))
    # - read the indicated number of pages from this point
    plxpages = []
    for _ in range(lx_obj.mapsize):
        lx_opm = LXOPMENTRY.read_from(instream)
        if lx_opm.flags in (OP32_ITERDATA, OP32_ITERDATA2):
            cbData += 4096
        else:
            cbData += lx_opm.size
        plxpages.append(lx_opm)
    if cbData >= lx_rte.offset + lx_rte.cb - 1:
        # Now read each page from its indicated location into our buffer
        pBuf = bytearray()
        for plxpage in plxpages:
            cbPageAddr = lx_hd.datapage + (plxpage.dataoffset << lx_hd.pageshift)
            instream.seek(cbPageAddr)
            data = instream.read(plxpage.size)
            if plxpage.flags == OP32_ITERDATA:
                pBuf.extend(_lx_unpack1(data))
            elif plxpage.flags == OP32_ITERDATA2:
                pBuf.extend(_lx_unpack2(data))
            elif plxpage.flags == OP32_VALID:
                pBuf.extend(data)
            else:
                continue
    return bytes(pBuf)


def _lx_unpack1(pBuf):
    """
    Unpacks a (max 4096-byte) page which has been compressed using the OS/2
    /EXEPACK1 method (a simple form of run-length encoding).

    This algorithm was derived from public-domain Pascal code by Veit
    Kannegieser (based on previous work by Max Alekseyev).
    """
    cbPage = len(pBuf)
    if cbPage > 4096:
        return pBuf
    ofIn  = 0;
    abOut = bytearray()
    while True:
        usReps = pBuf[ofIn] | (pBuf[ofIn+1] << 8)
        if not usReps:
            break
        ofIn += 2
        usLen = pBuf[ofIn] | (pBuf[ofIn+1] << 8)
        ofIn += 2
        if ofOut + usReps * usLen > 4096:
            break
        while usReps:
            abOut.extend(pBuf[ofIn:ofIn+usLen])
            usReps -= 1
        ofIn += usLen
        if ofIn > cbPage:
            break
    return bytes(abOut)


def _lx_unpack2(pBuf):
    """
    Unpacks a (max 4096-byte) page which has been compressed using the OS/2
    /EXEPACK2 method (which is apparently a modified Lempel-Ziv algorithm).

    This algorithm was derived from public-domain Pascal-and-x86-assembly
    code by Veit Kannegieser (based on previous work by Max Alekseyev).
    """
    cbPage = len(pBuf)
    if cbPage > 4096:
        return pBuf
    ofIn  = 0
    abOut = bytearray()
    while True:
        ulControl = int(le.uint16.from_bytes(pBuf, ofIn))
        # Bits 1 & 0 hold the case flag (0-3); the interpretation of the
        # remaining bits depend on the flag value.
        case_flag = ulControl & 0x3
        if case_flag == 0:
            # bits 15..8  = length2
            # bits  7..2  = length1
            if ulControl & 0xff == 0:
                # When length1 == 0, fill (length2) bytes with the byte
                # value following ulControl; if length2 is 0 we're done.
                ulLen = ulControl >> 8
                if not ulLen:
                    break
                # memset( abOut + ofOut, *(pBuf + ofIn + 2), ulLen );
                abOut.extend([pBuf[ofIn + 2]] * ulLen)
                ofIn += 3
            else:
                # block copy (length1) bytes from after ulControl
                ulLen = (ulControl & 0xff) >> 2
                # memcpy( abOut + ofOut, pBuf + ofIn + 1, ulLen );
                abOut.extend(pBuf[ofIn+1:ofIn+1+ulLen])
                ofIn  += ulLen + 1
        elif case_flag == 1:
            # bits 15..7     = backwards reference
            # bits  6..4  +3 = length2
            # bits  3..2     = length1
            # copy length1 bytes following ulControl
            ulLen = (ulControl >> 2) & 0x3;
            # memcpy( abOut + ofOut, pBuf + ofIn + 2, ulLen );
            abOut.extend(pBuf[ofIn+2:ofIn+2+ulLen])
            ofIn += ulLen + 2
            # get length2 from what's been unpacked already
            ulLen = (( ulControl >> 4 ) & 0x7 ) + 3
            _copy_byte_seq(abOut, -((ulControl >> 7) & 0x1FF), ulLen)
        elif case_flag == 2:
            # bits 15.. 4     = backwards reference
            # bits  3.. 2  +3 = length
            ulLen = (( ulControl >> 2 ) & 0x3 ) + 3
            _copy_byte_seq(abOut, -((ulControl >> 4) & 0xFFF), ulLen)
            ofIn  += 2
        elif case_flag == 3:
            ulControl = int(le.uint32.from_bytes(pBuf, ofIn))
            # bits 23..21  = ?
            # bits 20..12  = backwards reference
            # bits 11.. 6  = length2
            # bits  5.. 2  = length1
            # block copy (length1) bytes
            ulLen = (ulControl >> 2) & 0xF
            # memcpy( abOut + ofOut, pBuf + ofIn + 3, ulLen );
            abOut.extend(pBuf[ofIn+3 : ofIn+3+ulLen])
            ofIn  += ulLen + 3
            # copy (length2) bytes from previously-unpacked data
            ulLen = (ulControl >> 6) & 0x3F
            _copy_byte_seq(abOut, -((ulControl >> 12) & 0xFFF), ulLen)
        if ofIn >= cbPage:
            break
    # It seems that the unpacked data will always be 4096 bytes, except for
    # the final page (which will be taken care of when the caller uses the
    # total object length to read the concatenated buffer).
    return bytes(abOut)


def _copy_byte_seq(target, source_offset, count):
    """
    Perform a byte-over-byte iterative copy from one byte array into another,
    or from one point to another within the same array.  Used by LXUnpack2().
    Note that memcpy() does not work for this purpose, because the source and
    target address spaces could overlap - that is, the end of the source
    sequence could extend into the start of the target sequence, thus copying
    bytes that were previously written by the same call to this function.
    """
    for _ in range(count):
        target.append(target[source_offset])



from ..windows.ne import _NE_HEADER

# Resource table entry
# this diverges form the Windows format
NERTENTRY = le.Struct(
    etype='uint16',
    ename='uint16',
)

# https://www.pcjs.org/documents/books/mspl13/msdos/encyclopedia/appendix-k/
NESTENTRY = le.Struct(
    # Offset of segment relative to beginning
    # of file after shifting value left by alignment shift count
    sector='uint16',
    # Length of segment (0000H for segment of 65536 bytes)
    length='uint16',
    # Segment flag word
    segflag='uint16',
    # Minimum allocation size for segment
    minalloc='uint16',
)


def _read_os2_ne(instream):
    """Read an OS/2 16-bit NE executable."""
    # the header is the same as for the Windows NE format
    ne_offset = instream.tell()
    header = _NE_HEADER.read_from(instream)
    if header.target_os != 1:
        logging.warning('This is not an OS/2 NE file.')
    logging.debug(header)
    # parse the segment table
    cseg = header.segment_count
    seg_table = NESTENTRY.array(cseg).read_from(
        instream, ne_offset+header.seg_table_offset
    )
    logging.debug(seg_table)
    # parse the OS/2 resource table
    cres = header.number_res_table_entries
    res_table = NERTENTRY.array(cres).read_from(
        instream, ne_offset+header.res_table_offset
    )
    logging.debug(res_table)
    # locate resources
    # do something like http://www.edm2.com/0206/resources.html
    resources = []
    # first segment is start of file, skip
    for rte, ste in zip(res_table, seg_table[1:]):
        offset = ste.sector << header.file_alignment_size_shift_count
        if rte.etype != OS2RES_FONTFACE:
            logging.debug(
                'Skipping resource of type %d at %x', rte.etype, offset
            )
        else:
            logging.debug(
                'Reading font resource at %x', offset
            )
            instream.seek(offset)
            rsrc = instream.read(ste.length)
            resources.append(rsrc)
    return resources
