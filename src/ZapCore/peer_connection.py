import asyncio
import hashlib
import struct
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Constants
HANDSHAKE_LENGTH = 68
BLOCK_SIZE = 16 * 1024  #standard block size
DEFAULT_TIMEOUT = 10


async def download_piece(
    peer_ip: str,
    peer_port: int,
    info_hash: bytes,
    peer_id: bytes,
    piece_index: int,
    piece_length: int,
    expected_hash: bytes
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
            timeout=5
        )
        logger.debug(f"Connected to {peer_ip}:{peer_port}")

        # 2. Perform handshake
        if not await perform_handshake(reader, writer, info_hash, peer_id):
            logger.debug("Handshake failed")
            return None

        # 3. Message exchange (interested + wait for unchoke)
        if not await exchange_messages(reader, writer):
            logger.debug("Message exchange failed")
            return None

        # 4. Download piece(in blocks as per protocol)
        piece_data = await download_piece_blocks(
            reader,
            writer,
            piece_index,
            piece_length
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
) -> bool:
    
    """Handle protocol message exchange: interested -> unchoke"""
    
    # send interested message
    writer.write(b'\x00\x00\x00\x01\x02')  # interested
    await writer.drain()

    # wait for unchoke, handling intermediate messages
    while True:
        try:
            # read message length prefix
            length_bytes = await asyncio.wait_for(
                reader.readexactly(4),
                timeout=DEFAULT_TIMEOUT
            )
            length = struct.unpack(">I", length_bytes)[0]

            # keep-alive message
            if length == 0:
                continue

            # read message ID
            msg_id = (await asyncio.wait_for(
                reader.readexactly(1),
                timeout=DEFAULT_TIMEOUT
            ))[0]

            # handle bitfield (ID:5)
            if msg_id == 5:
                await asyncio.wait_for(
                    reader.readexactly(length - 1),
                    timeout=DEFAULT_TIMEOUT
                )
                continue

            # handle unchoke (ID:1)
            if msg_id == 1:
                return True

            # handle other messages by discarding payload
            if length > 1:
                await asyncio.wait_for(
                    reader.readexactly(length - 1),
                    timeout=DEFAULT_TIMEOUT
                )

        except asyncio.TimeoutError:
            logger.debug("Timeout waiting for unchoke")
            return False


async def download_piece_blocks(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    piece_index: int,
    piece_length: int
) -> Optional[bytes]:
    
    """Download piece in 16KB blocks"""
    
    piece_data = bytearray()

    for block_offset in range(0, piece_length, BLOCK_SIZE):
        block_size = min(BLOCK_SIZE, piece_length - block_offset)

        # request block
        if not await request_block(
            writer,
            piece_index,
            block_offset,
            block_size
        ):
            return None

        # receive block
        block_data = await receive_block(reader, block_size)
        if not block_data:
            return None

        piece_data.extend(block_data)

    return bytes(piece_data)


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
    reader: asyncio.StreamReader,
    expected_length: int
) -> Optional[bytes]:
    
    """Receive and validate block data"""
    
    try:
        # read length prefix(4 bytes)
        length_bytes = await asyncio.wait_for(
            reader.readexactly(4),
            timeout=DEFAULT_TIMEOUT
        )
        msg_length = struct.unpack(">I", length_bytes)[0]

        # read rest of the message 
        msg = await asyncio.wait_for(
            reader.readexactly(msg_length),
            timeout=DEFAULT_TIMEOUT
        )

        # validating message ID
        if msg[0] != 7:
            logger.debug(f"Invalid block message ID: {msg[0]}")
            return None

        # extracting piece index, offset and data
        piece_idx = struct.unpack(">I", msg[1:5])[0]
        offset = struct.unpack(">I", msg[5:9])[0]
        data = msg[9:]

        if len(data) != expected_length:
            logger.debug(f"Unexpected block size: got {len(data)} expected {expected_length}")
            return None

        return data

    except Exception as e:
        logger.debug(f"Block receive failed: {str(e)}")
        return None


def verify_piece(piece_data: bytes, expected_hash: bytes) -> bool:
    
    """Validate piece SHA1 hash"""
    
    actual_hash = hashlib.sha1(piece_data).digest()
    return actual_hash == expected_hash