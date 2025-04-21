import asyncio
import hashlib
import struct
import traceback
from typing import Dict

# constants
HANDSHAKE_LENGTH = 68
BLOCK_SIZE = 16 * 1024  # standard block size(as per the protocol !? or maybe it's good cause it's not too big to cause timeouts)


async def download_piece(
    peer_ip: str,
    peer_port: int,
    info_hash: bytes,
    peer_id: bytes,
    piece_index: int,
    piece_length: int,
    expected_hash: bytes,
    total_length: int
):
    
    """
    Handles downloading a single piece from a peer.

    Args:
        peer_ip (str): IP address of the peer.
        peer_port (int): Port number of the peer.
        info_hash (bytes): Torrent's info_hash.
        peer_id (bytes): This client's peer ID.
        piece_index (int): Index of the piece to download.
        piece_length (int): Length of the piece.
        expected_hash (bytes): Expected SHA-1 hash of the piece.
        total_length (int): Total length of the file.

    Returns:
        bytes or None: The downloaded and verified piece data, or None if failed.
    """
    
    reader, writer = None, None
    try:
        # 1. Establish connection with timeout
        try:
            # timeout of 10 seconds is added here cause some peers just never respond and we don't wanna hang forever.
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(peer_ip, peer_port),
                timeout=10  # 10 seconds good enough
            )
            print(f"[CONNECT] Connected to {peer_ip}:{peer_port}")
        except asyncio.TimeoutError:
            print(f"[CONNECT] Connection timed out with {peer_ip}:{peer_port}")
            return None
        except OSError as e:
            # got a weird WinError 121, GPT said it's just another timeout
            if hasattr(e, 'winerror') and e.winerror == 121:
                print(f"[CONNECT] WinError 121: Connection to {peer_ip}:{peer_port} timed out")
            else:
                print(f"[CONNECT] OSError with {peer_ip}:{peer_port}: {str(e)}")
            return None

        # 2. Perform handshake
        if not await perform_handshake(reader, writer, info_hash, peer_id):
            print(f"[HANDSHAKE] Handshake failed with {peer_ip}:{peer_port}")
            return None

        # 3. Message exchange with bitfield
        unchoked, bitfield = await exchange_messages(reader, writer)
        if not unchoked:
            print(f"[MESSAGE] Peer {peer_ip}:{peer_port} did not unchoke us")
            return None
            
        # Check if peer has this piece(some peers lie)
        if piece_index >= len(bitfield) or not bitfield[piece_index]:
            print(f"[MESSAGE] Peer {peer_ip}:{peer_port} does not have piece {piece_index}")
            return None

        # 4. Download piece
        await request_piece(writer, piece_index, piece_length, {"total_length": total_length, "piece count": (total_length + piece_length - 1) // piece_length})
        piece_data = await receive_piece(reader, piece_index, piece_length, {"total_length": total_length, "piece count": (total_length + piece_length - 1) // piece_length})
        
        if not piece_data:
            print(f"[DOWNLOAD] Failed to download piece {piece_index}")
            return None

        # 5. Verify hash(like 2FA)
        if not verify_piece(piece_data, expected_hash):
            print(f"[VERIFY] Piece {piece_index} failed hash check")
            return None

        print(f"[SUCCESS] Piece {piece_index} downloaded and verified successfully")
        return piece_data

    except asyncio.TimeoutError:
        print(f"[TIMEOUT] Connection timed out with {peer_ip}:{peer_port}")
        return None
    except ConnectionError as e:
        print(f"[CONNECT] Error with {peer_ip}:{peer_port}: {str(e)}")
        return None
    except Exception as e:
        print(f"[ERROR] Unexpected error with {peer_ip}:{peer_port}: {str(e)}")
        print(traceback.format_exc())
        return None
    
    # closing the connection cause who wants memory leaks
    finally:
        if writer:
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass


async def perform_handshake(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    info_hash: bytes,
    peer_id: bytes
):
    
    """
    Performs the BitTorrent handshake with a peer.

    Args:
        reader (asyncio.StreamReader): The stream reader used to receive data from the peer.
        writer (asyncio.StreamWriter): The stream writer used to send data to the peer.
        info_hash (bytes): The SHA-1 hash of the torrent's info dictionary.
        peer_id (bytes): This client's peer ID, typically a 20-byte string.

    Returns:
        bool: True if the handshake succeeded (i.e., the info_hash in the response matches),
              False otherwise.
    """
    # got this right after a hard time(should never blindly follow GPT)
    # Handshake format is: <pstrlen><pstr><reserved><info_hash><peer_id>
    handshake = (
        b'\x13' +                  # 1 byte(protocol length)
        b'BitTorrent protocol' +   # 19 bytes(pstr)
        b'\x00' * 8 +              # 8 bytes(reserved)
        info_hash +                # 20 bytes
        peer_id                    # 20 bytes
    ) # total-68 bytes

    writer.write(handshake)
    await writer.drain()

    try:
        # need to make sure we get the full handshake back
        response = await asyncio.wait_for(
            reader.readexactly(HANDSHAKE_LENGTH),
            timeout=10  
        )
        return response[28:48] == info_hash # validate info_hash in response
    
    except Exception as e:
        print(f"[HANDSHAKE] Error: {e}")
        return False


async def exchange_messages(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter
):
    
    """
    Sends an 'interested' message to the peer and waits for the 'unchoke' and 'bitfield' messages.

    Args:
        reader (asyncio.StreamReader): The stream reader used to receive data from the peer.
        writer (asyncio.StreamWriter): The stream writer used to send data to the peer.

    Returns:
        tuple: A tuple containing:
            - unchoked (bool): True if the 'unchoke' message was received, False otherwise.
            - bitfield (List[int]): The bitfield received from the peer, indicating the availability of pieces.
    """
    
    bitfield = []
    
    # Send interested message 
    writer.write(b'\x00\x00\x00\x01\x02')
    await writer.drain()
    print("[INTERESTED] Sent interested message to peer")

    try:
        # wait for unchoke message (some have a beef against us)
        async with asyncio.timeout(15):  # putting a longer timeout(inspired by aahan's code)
            while True:
                length_bytes = await reader.readexactly(4)
                length = struct.unpack(">I", length_bytes)[0]

                if length == 0:  # Keep-alive
                    continue

                msg_id = (await reader.readexactly(1))[0]

                # Handle bitfield (ID:5)
                if msg_id == 5:
                    bitfield_bytes = await reader.readexactly(length - 1)
                    # converting bytes to a list of bits (GPT explained)
                    bitfield = [
                        (byte >> (7 - i)) & 1
                        for byte in bitfield_bytes
                        for i in range(8)
                    ]
                    print(f"[MESSAGE] Received bitfield")
                    continue

                # Handle unchoke (ID:1)- what we need
                if msg_id == 1:
                    print(f"[MESSAGE] Received unchoke")
                    return True, bitfield

                # Handle "have" messages (ID:4) 
                if msg_id == 4 and length == 5:
                    piece_idx_bytes = await reader.readexactly(4)
                    piece_idx = struct.unpack(">I", piece_idx_bytes)[0]
                    
                    # Extend bitfield if needed- this prevents from getting an index error
                    if piece_idx >= len(bitfield):
                        bitfield.extend([0] * (piece_idx + 1 - len(bitfield)))
                    
                    bitfield[piece_idx] = 1
                    print(f"[HAVE] Peer announced it has piece {piece_idx}")
                    continue

                # Handle other messages(stuff which are not required)
                if length > 1:
                    await reader.readexactly(length - 1)

    except asyncio.TimeoutError:
        print(f"[MESSAGE] Timeout while waiting for messages")
        return False, []
    except asyncio.IncompleteReadError:
        print(f"[MESSAGE] Incomplete message received")
        return False, []
    except Exception as e:
        print(f"[MESSAGE] Error: {str(e)}")
        print(traceback.format_exc())
        return False, []


async def request_piece(
    writer: asyncio.StreamWriter,
    piece_index: int,
    piece_length: int,
    metadata: dict,
    block_size: int = 2**14
):
    
    """
    Sends a block request message to the peer.

    Args:
        writer (asyncio.StreamWriter): The stream writer used to send requests to the peer.
        piece_index (int): The index of the piece being requested.
        piece_length (int): The length of the piece being requested.
        metadata (dict): The metadata dictionary containing torrent information.
        block_size (int): The size of each block in bytes.

    Returns:
        bool: True if the request was successfully sent, False if an error occurred.
    """
    
    try:
        msg_len = 13
        msg_id = 6

        # handling the last piece cause it is shorter than the rest
        if piece_index == metadata.get("piece count") - 1:
            actual_length = (metadata.get("total_length") - (piece_index * piece_length))
        else:
            actual_length = piece_length

        # breaking the piece into blocks(this is what the protocol says)
        for offset in range(0, actual_length, block_size):
            this_block_size = min(block_size, actual_length - offset)
            message = struct.pack(">IBIII", msg_len, msg_id, piece_index, offset, this_block_size)
            writer.write(message)
            await writer.drain()
            print(f"[REQUEST] Requested block -> Piece: {piece_index} | Offset: {offset} | Length: {this_block_size}")
    except Exception as e:
        print("[REQUEST] Failed to send piece request to peer")
        print(traceback.format_exc())


async def receive_piece(
    reader: asyncio.StreamReader,
    piece_index: int,
    piece_length: int,
    metadata: dict,
):
    
    """
    Receives and validates a block of data from the peer.

    Args:
        reader (asyncio.StreamReader): The stream reader used to receive data from the peer.
        piece_index (int): The index of the piece being received.
        piece_length (int): The length of the piece being received.
        metadata (dict): The metadata dictionary containing torrent information.

    Returns:
        dict: A dictionary containing 'piece_index', 'offset', and 'data' if the block is valid.
        None: If the block message is invalid or an error occurs.
    """
    
    try:
        received_blocks = {}

        # same logic as request_piece for last piece size
        if piece_index == metadata.get("piece count") - 1:
            actual_length = (metadata.get("total_length") - (piece_index * piece_length))
        else:
            actual_length = piece_length

        # blocks can come in any order so just keep receiving them
        while (sum(len(block) for block in received_blocks.values()) < actual_length):
            msg_len_prefix = await asyncio.wait_for(reader.readexactly(4), timeout=10)
            msg_len = int.from_bytes(msg_len_prefix, "big")

            if msg_len == 0:  # Keep-alive message
                continue

            message = await reader.readexactly(msg_len)
            msg_id = message[0]

            if msg_id == 7:  # Piece message-what we need!
                idx = int.from_bytes(message[1:5], "big")
                begin = int.from_bytes(message[5:9], "big")
                block_data = message[9:]

                # making sure we are getting the right piece
                if idx != piece_index:
                    print(f"[RECEIVE] Got unexpected piece: requested {piece_index}, got {idx}")
                    continue

                received_blocks[begin] = block_data
                print(f"[RECEIVE] Got block at offset {begin} | Size {len(block_data)}")
            else:
                print(f"[RECEIVE] Ignoring message with ID: {msg_id}")

        # reconstruct piece in order(reason why we stored them by offset)
        full_piece = b''.join([received_blocks[offset] for offset in sorted(received_blocks)])
        return full_piece
        
    except asyncio.TimeoutError:
        print(f"[RECEIVE] Timeout while receiving blocks")
        return b''  # return empty bytes cause i was getting NoneType errors with None
    except Exception as e:
        print(f"[RECEIVE] Error: {str(e)}")
        print(traceback.format_exc())
        return b''  # same as above


def verify_piece(
    piece_data: bytes, 
    expected_hash: bytes
):
    
    """
    Validates the SHA1 hash of a piece of data.

    Args:
        piece_data (bytes): The data of the piece to verify.
        expected_hash (bytes): The expected SHA1 hash of the piece data.

    Returns:
        bool: True if the piece's hash matches the expected hash, False otherwise.
    """
    
    # simple - just validate if we got the right data
    actual_hash = hashlib.sha1(piece_data).digest()
    if actual_hash == expected_hash:
        print("[VERIFY] Piece hash verified")
        return True
    print("[VERIFY] Piece hash mismatch")
    return False


