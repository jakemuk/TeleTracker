import os
import json
import re
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
from pathlib import Path
from datetime import datetime

app = Flask(__name__, static_folder='web_viewer_static', static_url_path='')
CORS(app)

DOWNLOADS_DIR = Path('Downloads')

# Global caches
_message_cache = {}  # {file_path: (mtime, messages)} or {chat_id_filtered: (timestamp, filtered_messages)}
_chat_cache = {}  # {cache_key: chats_dict}
_cache_timestamps = {}  # Track file modification times


def parse_message_json(json_str):
    """Parse a single message JSON string from the concatenated file."""
    try:
        # Find the first complete JSON object
        brace_count = 0
        start_idx = -1
        in_string = False
        escape_next = False
        
        for i, char in enumerate(json_str):
            if escape_next:
                escape_next = False
                continue
            
            if char == '\\':
                escape_next = True
                continue
            
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
            
            if not in_string:
                if char == '{':
                    if start_idx == -1:
                        start_idx = i
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0 and start_idx != -1:
                        # Found complete JSON object
                        json_obj = json_str[start_idx:i+1]
                        remaining = json_str[i+1:].lstrip()
                        try:
                            message = json.loads(json_obj)
                            return message, remaining
                        except json.JSONDecodeError as e:
                            # Try to find next object
                            start_idx = -1
                            continue
        
        if start_idx != -1:
            # Last object might be incomplete, try anyway
            try:
                message = json.loads(json_str[start_idx:])
                return message, ""
            except json.JSONDecodeError:
                pass
        
        return None, json_str
    except Exception as e:
        print(f"Error parsing message: {e}")
        return None, json_str


def load_messages_from_json(file_path, use_cache=True):
    """Load all messages from a JSON file (which contains concatenated JSON objects)."""
    file_path = Path(file_path)
    
    # Check cache
    if use_cache:
        mtime = file_path.stat().st_mtime if file_path.exists() else 0
        if str(file_path) in _message_cache:
            cached_mtime, cached_messages = _message_cache[str(file_path)]
            if cached_mtime == mtime:
                return cached_messages
    
    messages = []
    try:
        # Use buffered reading for better performance
        with open(file_path, 'r', encoding='utf-8', buffering=8192) as f:
            content = f.read()
            
        remaining = content
        while remaining.strip():
            message, remaining = parse_message_json(remaining)
            if message:
                messages.append(message)
            else:
                break
        
        # Cache the results
        if use_cache and file_path.exists():
            mtime = file_path.stat().st_mtime
            _message_cache[str(file_path)] = (mtime, messages)
    except Exception as e:
        print(f"Error loading messages from {file_path}: {e}")
    
    return messages


def load_messages_from_txt(file_path):
    """Load messages from TXT file and convert to structured format."""
    messages = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Split by double newlines (message separator)
        message_blocks = content.split('\n\n')
        
        for block in message_blocks:
            if not block.strip():
                continue
            
            message = {}
            lines = block.strip().split('\n')
            
            for line in lines:
                if line.startswith('Message ID:'):
                    message['id'] = int(line.split(':', 1)[1].strip())
                elif line.startswith('From User ID:'):
                    parts = line.split(' - Username:')
                    if len(parts) == 2:
                        user_id = parts[0].split(':', 1)[1].strip()
                        username = parts[1].strip()
                        message['from_user'] = {
                            'id': int(user_id),
                            'username': username
                        }
                elif line.startswith('Date:'):
                    message['date'] = line.split(':', 1)[1].strip()
                elif line.startswith('Text:'):
                    message['text'] = line.split(':', 1)[1].strip() if ':' in line else ''
                elif line.startswith('Reply_markup:'):
                    message['reply_markup'] = line.split(':', 1)[1].strip() if ':' in line else None
            
            if message:
                messages.append(message)
    except Exception as e:
        print(f"Error loading messages from {file_path}: {e}")
    
    return messages


@app.route('/')
def index():
    """Serve the main HTML page."""
    return send_from_directory('web_viewer_static', 'index.html')


def get_chat_key(chat_data):
    """Generate a unique key for a chat based on its ID and username."""
    if not chat_data:
        return None
    chat_id = chat_data.get('id')
    username = chat_data.get('username', '')
    # Use chat ID as primary key, username as secondary
    return f"{chat_id}_{username}" if username else str(chat_id)


def discover_all_chats(use_cache=True):
    """Scan all message files and discover unique chats."""
    cache_key = 'all_chats'
    
    # Check if we need to refresh cache
    if use_cache and cache_key in _chat_cache:
        # Check if any files have been modified
        needs_refresh = False
        if not DOWNLOADS_DIR.exists():
            return _chat_cache[cache_key]
        
        for chat_dir in DOWNLOADS_DIR.iterdir():
            if not chat_dir.is_dir():
                continue
            logs_dir = chat_dir / 'logs'
            if not logs_dir.exists():
                continue
            
            json_file = logs_dir / f'{chat_dir.name}_bot.json'
            if json_file.exists():
                mtime = json_file.stat().st_mtime
                if str(json_file) not in _cache_timestamps or _cache_timestamps[str(json_file)] != mtime:
                    needs_refresh = True
                    break
        
        if not needs_refresh:
            return _chat_cache[cache_key]
    
    chats_dict = {}

    if not DOWNLOADS_DIR.exists():
        _chat_cache[cache_key] = chats_dict
        return chats_dict

    # New-style chat folders carry a metadata.json (written by the downloader).
    # Present each such folder as a SINGLE chat holding all of its messages: a
    # linked channel's posts are saved in the same folder but with a different
    # chat id, so we must NOT split the folder on chat id.
    metadata_folders = set()
    for chat_dir in DOWNLOADS_DIR.iterdir():
        if not chat_dir.is_dir():
            continue
        meta_file = chat_dir / 'metadata.json'
        if not meta_file.exists():
            continue
        metadata_folders.add(chat_dir.name)
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                meta = json.load(f)
        except Exception:
            meta = {}
        json_file = chat_dir / 'logs' / f'{chat_dir.name}_bot.json'
        count = 0
        if json_file.exists():
            messages = load_messages_from_json(json_file, use_cache=use_cache)
            count = len({m.get('id') for m in messages
                         if isinstance(m, dict) and m.get('id') is not None})
            _cache_timestamps[str(json_file)] = json_file.stat().st_mtime
        chats_dict[chat_dir.name] = {
            'id': chat_dir.name,
            'chat_id': meta.get('chat_id'),
            'username': meta.get('username'),
            'name': meta.get('name') or chat_dir.name,
            'type': meta.get('type', ''),
            'message_count': count,
            'source_folder': chat_dir.name,
            'folder_chat': True,
        }

    # Scan remaining (legacy per-sender) folders, grouping by chat id as before.
    for chat_dir in DOWNLOADS_DIR.iterdir():
        if not chat_dir.is_dir():
            continue
        if chat_dir.name in metadata_folders:
            continue

        logs_dir = chat_dir / 'logs'
        if not logs_dir.exists():
            continue

        # Try JSON files first
        json_file = logs_dir / f'{chat_dir.name}_bot.json'
        if json_file.exists():
            # Only scan first few messages to discover chats (much faster)
            messages = load_messages_from_json(json_file, use_cache=use_cache)
            
            # Track seen chat keys to avoid duplicates
            seen_chats = set()
            
            # Sample messages to discover chats (check first 100 and last 100)
            sample_size = min(200, len(messages))
            if sample_size > 0:
                sample_indices = list(range(min(100, len(messages)))) + list(range(max(0, len(messages) - 100), len(messages)))
                for idx in sample_indices:
                    if idx < len(messages):
                        msg = messages[idx]
                        if 'chat' in msg and msg['chat']:
                            chat_data = msg['chat']
                            chat_key = get_chat_key(chat_data)
                            if chat_key and chat_key not in seen_chats:
                                seen_chats.add(chat_key)
                                # Create chat info
                                chat_name = chat_data.get('username') or chat_data.get('first_name') or chat_data.get('title') or str(chat_data.get('id', 'Unknown'))
                                chats_dict[chat_key] = {
                                    'id': chat_key,
                                    'chat_id': chat_data.get('id'),
                                    'username': chat_data.get('username'),
                                    'name': chat_name,
                                    'type': chat_data.get('type', ''),
                                    'message_count': 0,  # Will be calculated on demand
                                    'source_folder': chat_dir.name
                                }
            
            # Count messages per chat (do this efficiently)
            chat_counts = {}
            for msg in messages:
                if 'chat' in msg and msg['chat']:
                    chat_data = msg['chat']
                    chat_key = get_chat_key(chat_data)
                    if chat_key:
                        chat_counts[chat_key] = chat_counts.get(chat_key, 0) + 1
            
            # Update message counts
            for chat_key, count in chat_counts.items():
                if chat_key in chats_dict:
                    chats_dict[chat_key]['message_count'] = count
                elif chat_key not in seen_chats:
                    # Chat discovered during counting
                    chat_data = None
                    for msg in messages:
                        if 'chat' in msg and msg['chat']:
                            test_chat = msg['chat']
                            if get_chat_key(test_chat) == chat_key:
                                chat_data = test_chat
                                break
                    if chat_data:
                        chat_name = chat_data.get('username') or chat_data.get('first_name') or chat_data.get('title') or str(chat_data.get('id', 'Unknown'))
                        chats_dict[chat_key] = {
                            'id': chat_key,
                            'chat_id': chat_data.get('id'),
                            'username': chat_data.get('username'),
                            'name': chat_name,
                            'type': chat_data.get('type', ''),
                            'message_count': count,
                            'source_folder': chat_dir.name
                        }
            
            # Store file mtime for cache invalidation
            if json_file.exists():
                _cache_timestamps[str(json_file)] = json_file.stat().st_mtime
        
        # Also check TXT files as fallback (if no JSON file found)
        txt_file = logs_dir / f'{chat_dir.name}_bot.txt'
        if txt_file.exists():
            # Check if we already have chats from JSON for this folder
            has_json_chats = any(c.get('source_folder') == chat_dir.name for c in chats_dict.values())
            if not has_json_chats:
                # For TXT files, we can't determine chat info easily, so use folder name
                txt_chat_key = f"txt_{chat_dir.name}"
                if txt_chat_key not in chats_dict:
                    chats_dict[txt_chat_key] = {
                        'id': txt_chat_key,
                        'chat_id': None,
                        'username': None,
                        'name': chat_dir.name,
                        'type': 'unknown',
                        'message_count': 0,
                        'source_folder': chat_dir.name
                    }
    
    # Prefer explicit per-chat metadata (written by the downloader) for display
    # fields, so the chat name/type are reliable even when messages don't carry
    # full chat info (media-only or service-message-only chats).
    for chat in chats_dict.values():
        folder = chat.get('source_folder')
        if not folder:
            continue
        meta_file = DOWNLOADS_DIR / folder / 'metadata.json'
        if meta_file.exists():
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
            except Exception:
                continue
            if meta.get('name'):
                chat['name'] = meta['name']
            if meta.get('type'):
                chat['type'] = meta['type']

    # Cache the results
    if use_cache:
        _chat_cache[cache_key] = chats_dict

    return chats_dict


@app.route('/api/chats')
def get_chats():
    """Get list of all available chats grouped by actual chat ID."""
    chats_dict = discover_all_chats()
    chats = list(chats_dict.values())
    return jsonify(sorted(chats, key=lambda x: x['name'].lower()))


@app.route('/api/chats/<chat_id>/messages')
def get_messages(chat_id):
    """Get messages for a specific chat with pagination."""
    chats_dict = discover_all_chats()
    
    if chat_id not in chats_dict:
        return jsonify({'error': 'Chat not found'}), 404
    
    chat_info = chats_dict[chat_id]
    source_folder = chat_info.get('source_folder')
    target_chat_id = chat_info.get('chat_id')
    target_username = chat_info.get('username')
    
    # Get pagination parameters
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 100))

    # New-style chat folder: serve every message in the folder (deduped by id),
    # so a group and its linked channel's posts appear together as one
    # conversation instead of split across two same-named entries.
    if chat_info.get('folder_chat'):
        json_file = DOWNLOADS_DIR / source_folder / 'logs' / f'{source_folder}_bot.json'
        msgs = load_messages_from_json(json_file) if json_file.exists() else []
        msgs = [m for m in msgs if isinstance(m, dict)]
        msgs.sort(key=lambda x: x.get('id', 0), reverse=True)
        seen, deduped = set(), []
        for m in msgs:
            mid = m.get('id')
            if mid is not None and mid in seen:
                continue
            seen.add(mid)
            deduped.append(m)
        total = len(deduped)
        start_idx = (page - 1) * per_page
        return jsonify({
            'messages': deduped[start_idx:start_idx + per_page],
            'pagination': {
                'page': page, 'per_page': per_page, 'total': total,
                'pages': (total + per_page - 1) // per_page
            }
        })

    # Check cache key for filtered messages
    cache_key = f"{chat_id}_filtered"

    # A chat's messages can be split across multiple sender folders (the
    # downloader saves each message under its sender's username), so aggregate
    # across ALL download folders rather than just the recorded source_folder.
    all_messages = []
    if chat_id.startswith('txt_'):
        # TXT-only chat: read just its own folder.
        txt_file = DOWNLOADS_DIR / source_folder / 'logs' / f'{source_folder}_bot.txt'
        if txt_file.exists():
            all_messages = load_messages_from_txt(txt_file)
    elif DOWNLOADS_DIR.exists():
        for folder in DOWNLOADS_DIR.iterdir():
            if not folder.is_dir():
                continue
            json_file = folder / 'logs' / f'{folder.name}_bot.json'
            if json_file.exists():
                all_messages.extend(load_messages_from_json(json_file, use_cache=True))
    
    # Filter messages to only include those from the target chat
    # Cache filtered results per chat
    if cache_key not in _message_cache or not all_messages:
        filtered_messages = []
        for msg in all_messages:
            if 'chat' in msg and msg['chat']:
                msg_chat = msg['chat']
                msg_chat_id = msg_chat.get('id')
                msg_username = msg_chat.get('username', '')
                
                # Match by chat ID and username
                if msg_chat_id == target_chat_id:
                    if target_username:
                        # If we have a username, match it too
                        if msg_username == target_username:
                            filtered_messages.append(msg)
                    else:
                        # No username, just match by ID
                        filtered_messages.append(msg)
            elif chat_id.startswith('txt_'):
                # For TXT files, include all messages
                filtered_messages.append(msg)
        
        # Sort by message ID (newest first)
        filtered_messages.sort(key=lambda x: x.get('id', 0), reverse=True)

        # De-duplicate by message id: logs are append-only (so re-downloads
        # repeat messages) and a chat's messages may be aggregated from several
        # folders, which can surface the same message more than once.
        seen_ids = set()
        deduped = []
        for m in filtered_messages:
            mid = m.get('id')
            if mid is not None and mid in seen_ids:
                continue
            seen_ids.add(mid)
            deduped.append(m)
        filtered_messages = deduped

        # Cache filtered messages
        _message_cache[cache_key] = (datetime.now().timestamp(), filtered_messages)
    else:
        _, filtered_messages = _message_cache[cache_key]
    
    # Apply pagination
    total = len(filtered_messages)
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_messages = filtered_messages[start_idx:end_idx]
    
    return jsonify({
        'messages': paginated_messages,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total,
            'pages': (total + per_page - 1) // per_page
        }
    })


@app.route('/api/chats/<chat_id>/info')
def get_chat_info(chat_id):
    """Get chat information."""
    chats_dict = discover_all_chats()
    
    if chat_id not in chats_dict:
        return jsonify({'error': 'Chat not found'}), 404
    
    return jsonify(chats_dict[chat_id])


if __name__ == '__main__':
    # Create static directory if it doesn't exist
    os.makedirs('web_viewer_static', exist_ok=True)
    app.run(debug=True, port=5000, host='0.0.0.0')

