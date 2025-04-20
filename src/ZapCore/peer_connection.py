import asyncio
import hashlib
import struct
import logging
from typing import Optional, Tuple, List, Dict, Union

logger = logging.getLogger(__name__)

# Constants
HANDSHAKE_LENGTH = 68
BLOCK_SIZE = 16 * 1024  #standard block size
DEFAULT_TIMEOUT = 5


async def download_piece(
    peer_ip: str,
    peer_port: int,
    info_hash: bytes,
    peer_id: bytes,
    piece_index: int,
    piece_length: int,
    expected_hash: bytes,
    total_length: int
) -> Optional[bytes]:
    
    """
    Complete piece download workflow with proper protocol compliance.
    Handles connection, handshake, messaging, and block downloads.
    """
    
    reader, writer = None, None
    try:
        # 1. Establish connection
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(peer_ip, peer_port),
            timeout=DEFAULT_TIMEOUT
        )
        logger.debug(f"Connected to {peer_ip}:{peer_port}")

        # 2. Perform handshake
        if not await perform_handshake(reader, writer, info_hash, peer_id):
            logger.debug("Handshake failed")
            return None

        # 3. Message exchange with bitfield support
        unchoked, bitfield = await exchange_messages(reader, writer)
        if not unchoked:
            logger.debug("Peer did not unchoke us")
            return None
            
        # Check if peer has this piece
        if piece_index >= len(bitfield) or not bitfield[piece_index]:
            logger.debug(f"Peer doesn't have piece {piece_index}")
            return None

        # 4. Download piece with out-of-order block support
        piece_data = await download_piece_blocks(
            reader,
            writer,
            piece_index,
            piece_length,
            total_length  # Pass total_length for final piece
        )
        if not piece_data:
            return None

        # 5. Verify hash
        if not verify_piece(piece_data, expected_hash):
            logger.debug("Piece verification failed")
            return None

        return piece_data

    except (asyncio.TimeoutError, ConnectionError, ValueError) as e:
        logger.debug(f"Download failed: {type(e).__name__}: {str(e)}")
        return None
    
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()


async def perform_handshake(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    info_hash: bytes,
    peer_id: bytes
) -> bool:
    
    """Execute BitTorrent handshake protocol"""
    
    handshake = (
        b'\x13' +                  ##1 byte(protocol length)
        b'BitTorrent protocol' +   #19 bytes(pstr)
        b'\x00' * 8 +              #8 bytes(reserved)
        info_hash +                #20 bytes
        peer_id                    #20 bytes
    ) # total-68 bytes

    writer.write(handshake)
    await writer.drain()

    try:
        response = await asyncio.wait_for(
            reader.readexactly(HANDSHAKE_LENGTH),
            timeout=DEFAULT_TIMEOUT
        )
        return response[28:48] == info_hash #validate info_hash in response
    
    except Exception as e:
        logger.debug(f"Handshake error: {str(e)}")
        return False


async def exchange_messages(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter
) -> Tuple[bool, List[bool]]:
    
    """Handle protocol message exchange: interested -> unchoke"""
    
    bitfield = []
    
    # Send interested message
    writer.write(b'\x00\x00\x00\x01\x02')
    await writer.drain()

    while True:
        try:
            length_bytes = await asyncio.wait_for(
                reader.readexactly(4),
                timeout=DEFAULT_TIMEOUT
            )
            length = struct.unpack(">I", length_bytes)[0]

            if length == 0:  # Keep-alive
                continue

            msg_id = (await asyncio.wait_for(
                reader.readexactly(1),
                timeout=DEFAULT_TIMEOUT
            ))[0]

            # Handle bitfield (ID:5)
            if msg_id == 5:
                bitfield_bytes = await asyncio.wait_for(
                    reader.readexactly(length - 1),
                    timeout=DEFAULT_TIMEOUT
                )
                bitfield = [
                    (byte >> (7 - i)) & 1
                    for byte in bitfield_bytes
                    for i in range(8)
                ]
                continue

            # Handle unchoke (ID:1)
            if msg_id == 1:
                return True, bitfield

            # Handle other messages
            if length > 1:
                await asyncio.wait_for(
                    reader.readexactly(length - 1),
                    timeout=DEFAULT_TIMEOUT
                )

        except asyncio.TimeoutError:
            return False, []
        except asyncio.IncompleteReadError:
            return False, []


async def download_piece_blocks(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    piece_index: int,
    piece_length: int,
    total_length: int
) -> Optional[bytes]:
    
    """Download piece in 16KB blocks"""
    
    received_blocks: Dict[int, bytes] = {}
    
    # calculate actual piece length (for final piece)
    if piece_index == (total_length - 1) // piece_length:
        actual_length = total_length - (piece_index * piece_length)
    else:
        actual_length = piece_length

    # request blocks
    for block_offset in range(0, actual_length, BLOCK_SIZE):
        block_size = min(BLOCK_SIZE, actual_length - block_offset)
        
        if not await request_block(
            writer, 
            piece_index, 
            block_offset, 
            block_size
        ):
            return None

    # receive blocks (out-of-order)
    while sum(len(b) for b in received_blocks.values()) < actual_length:
        block = await receive_block(reader)
        
        if not block or block["piece_index"] != piece_index:
            continue
        
        received_blocks[block["offset"]] = block["data"]

    # reconstruct piece in order
    return b''.join([received_blocks[o] for o in sorted(received_blocks)])



async def request_block(
    writer: asyncio.StreamWriter,
    piece_index: int,
    block_offset: int,
    block_length: int
) -> bool:
    
    """Send block request message"""
    
    try:
        request = (
            b'\x00\x00\x00\x0d\x06' +  # request (13 bytes)
            struct.pack(">I", piece_index) +
            struct.pack(">I", block_offset) +
            struct.pack(">I", block_length)
        )
        writer.write(request)
        await writer.drain()
        return True
    except Exception as e:
        logger.debug(f"Request failed: {str(e)}")
        return False


async def receive_block(
    reader: asyncio.StreamReader
) -> Optional[Dict[str, Union[int, bytes]]]:
    
    """Receive and validate block data"""
    
    try:
        length_bytes = await asyncio.wait_for(
            reader.readexactly(4),
            timeout=DEFAULT_TIMEOUT
        )
        msg_length = struct.unpack(">I", length_bytes)[0]

        msg = await asyncio.wait_for(
            reader.readexactly(msg_length),
            timeout=DEFAULT_TIMEOUT
        )

        if msg[0] != 7:  #piece message
            return None

        return {
            "piece_index": struct.unpack(">I", msg[1:5])[0],
            "offset": struct.unpack(">I", msg[5:9])[0],
            "data": msg[9:]
        }
    except Exception as e:
        logger.debug(f"Block receive failed: {str(e)}")
        return None


def verify_piece(piece_data: bytes, expected_hash: bytes) -> bool:
    
    """Validate piece SHA1 hash"""
    
    actual_hash = hashlib.sha1(piece_data).digest()
    return actual_hash == expected_hash