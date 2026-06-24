import pyrogram
import json
from dotenv import load_dotenv
import os
import random

load_dotenv()

api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')


def get_file_info(data):
  media_type = ""
  random_numbers = [random.randint(1, 100) for _ in range(6)]
  if data.media is not None:
    try:
      for key in ['document', 'photo', 'video', 'location', 'voice', 'audio']:
        if key in str(data):
          media_type = key
          break
      if media_type == "document":
        return (data.document.file_id, data.document.file_name)
      elif media_type == "photo":
        return (data.photo.file_id, f"{random_numbers}.png")
      elif media_type == "video":
        return (data.video.file_id, data.video.file_name)
      elif media_type == "location":
        return (data.location.file_id, data.location.file_name)
      elif media_type == "voice":
        return (data.voice.file_id, data.voice.file_name)
      elif media_type == "audio":
        return (data.audio.file_id, data.audio.file_name)
      else:
        return (None, None)
    except Exception as e:
      print(f"Error: {e}")
      return (None, None)


def parse_and_print_message(message):
  print("=" * 20 + "\n")
  message_dict = message.__dict__
  for key, value in message_dict.items():
    if value not in [None, False]:
      print(f"{key}: {value}")
  print("\n")
  print("=" * 20 + "\n")


def write_chat_metadata(chat_id, chat):
  """Write a small metadata.json in the chat's folder so the web viewer can
  show the chat name/type reliably, instead of parsing it out of message
  bodies (which fails for media-only or service-message-only chats)."""
  directory = f'Downloads/{chat_id}'
  if not os.path.exists(directory):
    os.makedirs(directory)
  name = (getattr(chat, 'title', None) or getattr(chat, 'username', None)
          or getattr(chat, 'first_name', None) or str(chat_id))
  metadata = {
    'chat_id': getattr(chat, 'id', chat_id),
    'name': name,
    'title': getattr(chat, 'title', None),
    'username': getattr(chat, 'username', None),
    'first_name': getattr(chat, 'first_name', None),
    'type': str(getattr(chat, 'type', '')),
    'members_count': getattr(chat, 'members_count', None),
  }
  try:
    with open(f'{directory}/metadata.json', 'w', encoding='utf-8') as f:
      json.dump(metadata, f, ensure_ascii=False, indent=2)
  except Exception as e:
    print(f"Could not write chat metadata: {e}")


def process_messages(bot_token, chat_id, num_messages, message_id):
  directory = f'sessions/{chat_id}'
  if not os.path.exists(directory):
    os.makedirs(directory)
  bot_token_filename = bot_token.replace(":", "_").replace("/", "_")
  bot_token_filename = f"{directory}/{bot_token_filename}.session"
  app = pyrogram.Client(bot_token_filename, api_id, api_hash)

  async def main(num_messages, message_id):
    # Download every existing message with id in [lower, message_id], newest
    # first. Telegram serves up to 200 ids per get_messages call, so fetch in
    # batches over a single open connection instead of reconnecting per message
    # (far fewer round-trips and flood-waits when downloading a whole chat).
    lower = max(1, message_id - num_messages + 1)
    # Ids already saved on a previous run (parsed from the readable log), so we
    # neither re-fetch nor re-save them: repeat/update runs only get new ones.
    txt_path = f'Downloads/{chat_id}/logs/{chat_id}_bot.txt'
    existing_ids = set()
    if os.path.exists(txt_path):
      try:
        # utf-8-sig tolerates a stray BOM if the log was ever rewritten by hand.
        with open(txt_path, encoding='utf-8-sig') as f:
          for line in f:
            if line.startswith('Message ID: '):
              try:
                existing_ids.add(int(line[len('Message ID: '):].strip()))
              except ValueError:
                pass
      except Exception as e:
        print(f"[-] Could not read existing log: {e}")
    if existing_ids:
      print(f"[*] {len(existing_ids)} messages already downloaded; fetching only new ones.")
    metadata_written = False
    saved = 0
    BATCH = 200
    try:
      async with app:
        hi = message_id
        while hi >= lower:
          lo = max(lower, hi - BATCH + 1)
          ids = list(range(hi, lo - 1, -1))  # newest first
          batch = await app.get_messages(chat_id, ids)
          if not isinstance(batch, list):
            batch = [batch]
          real_in_batch = 0
          skipped_existing = 0
          for messages in batch:
            # kurigram returns None for a missing/deleted message id; skip gaps.
            if messages is None or messages.date is None:
              continue
            real_in_batch += 1
            if messages.id in existing_ids:
              skipped_existing += 1
              continue  # already downloaded on a previous run
            # Isolate each message: a single bad/odd message (e.g. a web-page
            # preview with no real media) must not abort the whole download.
            try:
              parse_and_print_message(messages)
              # Record chat metadata once, from the first real message we see.
              if not metadata_written and messages.chat is not None:
                write_chat_metadata(chat_id, messages.chat)
                metadata_written = True
              if messages.media is not None:
                file_id, file_name = get_file_info(messages)
                # Skip media we can't resolve to a real file (web-page previews
                # etc. return no file_id).
                if file_id is not None:
                  file_name = f"downloads/{chat_id}/{messages.id}_{file_name}"
                  # Keep track of the progress while downloading
                  async def progress(current, total, _fn=file_name):
                    if total != 0:
                      print(f"{current * 100 / total:.1f}%")
                    else:
                      print(f"[*] Download of {_fn.split('/')[-1]} is complete!")

                  try:
                    await app.download_media(
                        file_id,
                        file_name=file_name,
                        progress=progress,
                    )
                  except Exception as e:
                    print(f"[-] Could not download media for message {messages.id}: {e}")
              # Save to file, always grouped by chat so the full chat history
              # stays together regardless of which user sent each message. The
              # sender is still recorded per-message in the log below.
              directory = f'Downloads/{chat_id}/logs'
              if not os.path.exists(directory):
                os.makedirs(directory)
              with open(f'{directory}/{chat_id}_bot.txt', 'a', encoding='utf-8') as file:
                file.write(f"Message ID: {messages.id}\n")
                if messages.from_user is not None:
                  file.write(
                      f"From User ID: {messages.from_user.id} - Username: {messages.from_user.username}\n"
                  )
                file.write(f"Date: {messages.date}\n")
                file.write(f"Text: {messages.text}\n")
                file.write(f"Reply_markup: {messages.reply_markup}\n\n")
              # Save the whole message to a file
              with open(f'{directory}/{chat_id}_bot.json', 'a', encoding='utf-8') as file:
                file.write(str(messages))
              existing_ids.add(messages.id)
              saved += 1
            except Exception as e:
              print(f"[-] Error processing message {getattr(messages, 'id', '?')}: {e}")
              continue
          print(f"[*] {saved} new messages saved (scanned ids {lo}-{hi})")
          # Stop once a whole batch of real messages is already downloaded:
          # going newest-first, everything older is already saved too.
          if real_in_batch > 0 and skipped_existing == real_in_batch:
            print("[*] Reached already-downloaded messages; stopping early.")
            break
          hi = lo - 1
    except Exception as e:
      print(f"Error: {e}")
    print(f"[*] Done. {saved} new messages saved to Downloads/{chat_id}/")

  try:
    # kurigram's Client.run() no longer accepts a coroutine (it only takes
    # keyword args), unlike the old Pyrogram. Run the coroutine on the client's
    # event loop directly, which is exactly what Pyrogram's run(coroutine) did.
    app.loop.run_until_complete(main(num_messages, message_id))
  except KeyboardInterrupt:
    print("\nStopping...")
    app.disconnect()
    pass
