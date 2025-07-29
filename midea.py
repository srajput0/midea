import os
import json
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8396790178:AAGdB6U1SahvrhUyG8xCMCRYaHVNpvlMGx8"
LOG_GROUP_ID = -1001902619247  # Replace with your log group ID (negative number)

class ReplySaveBot:
    def __init__(self):
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.setup_storage()
        self.setup_handlers()
        
    def setup_storage(self):
        """Setup storage directories and database"""
        # Create media directories
        self.base_dir = Path("saved_media")
        self.media_dirs = {
            'video': self.base_dir / "videos",
            'photo': self.base_dir / "photos",
            'audio': self.base_dir / "audio",
            'voice': self.base_dir / "voice",
            'video_note': self.base_dir / "video_notes",
            'document': self.base_dir / "documents",
            'animation': self.base_dir / "animations"
        }
        
        # Create all directories
        for directory in self.media_dirs.values():
            directory.mkdir(parents=True, exist_ok=True)
            
        # Setup database
        self.setup_database()
        
    def setup_database(self):
        """Setup SQLite database for saved media tracking"""
        self.db_path = self.base_dir / "saved_media.db"
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS saved_media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT UNIQUE NOT NULL,
                media_type TEXT NOT NULL,
                original_filename TEXT,
                saved_filename TEXT,
                file_path TEXT,
                file_size INTEGER,
                user_id INTEGER,
                username TEXT,
                user_first_name TEXT,
                chat_id INTEGER,
                message_id INTEGER,
                caption TEXT,
                save_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                saved_by_user_id INTEGER,
                saved_by_username TEXT,
                mime_type TEXT,
                duration INTEGER,
                width INTEGER,
                height INTEGER
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Database setup complete")
        
    def setup_handlers(self):
        """Setup command handlers"""
        # Save command handler (only works as reply)
        self.application.add_handler(
            CommandHandler("save", self.save_command, filters=filters.REPLY)
        )
        
        # Get media command
        self.application.add_handler(
            CommandHandler("get", self.get_command)
        )
        
        # Stats command
        self.application.add_handler(
            CommandHandler("stats", self.stats_command)
        )
        
        # List saved media command
        self.application.add_handler(
            CommandHandler("list", self.list_command)
        )
        
        # Search command
        self.application.add_handler(
            CommandHandler("search", self.search_command)
        )
        
        # Start command
        self.application.add_handler(
            CommandHandler("start", self.start_command)
        )
        
        # Message handler for media name requests (non-command messages)
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_media_request)
        )

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        start_text = """
🤖 **Reply Save Bot** 

📋 **How to use:**
1. Send any media (video, photo, audio, etc.) to your log group
2. Reply to that media with `/save` command
3. The media will be saved to the bot's storage

📥 **How to retrieve media:**
1. Send media filename to get the file
2. Or use `/get <filename>` command

📌 **Commands:**
• `/save` - Save media (reply to media)
• `/get <filename>` - Get saved media by filename
• `/stats` - Show saved media statistics  
• `/list` - List recent saved media
• `/search <query>` - Search saved media

🏷️ **Supported Media:**
• Videos 📹
• Photos 📸
• Audio files 🎵
• Voice messages 🎤
• Documents 📄
• Animations/GIFs 🎬
• Video notes (round videos) 📹

💡 **Tips:**
• Just send the filename (without path) to get media
• Use partial filenames for search
• The bot works in your log group: `{LOG_GROUP_ID}`
        """
        await update.message.reply_text(start_text)

    async def save_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /save command - only works as reply to media"""
        # Check if it's in the log group
        if update.effective_chat.id != LOG_GROUP_ID:
            await update.message.reply_text(
                "❌ This command only works in the designated log group!"
            )
            return
            
        # Get the replied message
        replied_message = update.message.reply_to_message
        
        if not replied_message:
            await update.message.reply_text(
                "❌ Please reply to a media message with /save command!"
            )
            return
            
        # Check if the replied message contains media
        media_info = self.extract_media_info(replied_message)
        
        if not media_info:
            await update.message.reply_text(
                "❌ The replied message doesn't contain any saveable media!"
            )
            return
            
        # Add save information
        media_info['saved_by_user_id'] = update.effective_user.id
        media_info['saved_by_username'] = update.effective_user.username
        media_info['save_message_id'] = update.message.message_id
        
        # Save the media
        saved_path = await self.save_media(context, replied_message, media_info)
        
        if saved_path:
            # Save to database
            self.save_to_database(media_info)
            
            # Send confirmation
            await update.message.reply_text(
                f"✅ **Media Saved Successfully!**\n\n"
                f"📁 **File:** `{saved_path.name}`\n"
                f"📂 **Type:** {media_info['media_type'].title()}\n"
                f"📊 **Size:** {self.format_file_size(media_info.get('file_size', 0))}\n"
                f"👤 **Original Sender:** {media_info.get('user_first_name', 'Unknown')}\n"
                f"💾 **Saved By:** {update.effective_user.first_name}\n"
                f"📅 **Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"💡 **To retrieve:** Send `{saved_path.name}` or use `/get {saved_path.name}`",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ Failed to save media. Please try again."
            )

    async def get_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /get command to retrieve media by filename"""
        if not context.args:
            await update.message.reply_text(
                "📥 **Usage:** `/get <filename>`\n"
                "Example: `/get 20241129_143022_video.mp4`",
                parse_mode='Markdown'
            )
            return
            
        filename = ' '.join(context.args)
        await self.send_media_by_filename(update, filename)

    async def handle_media_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle non-command text messages as potential media filename requests"""
        message_text = update.message.text.strip()
        
        # Skip if message is too short or looks like regular conversation
        if len(message_text) < 5 or ' ' in message_text:
            return
            
        # Check if it looks like a filename (has extension or timestamp pattern)
        if ('.' in message_text or 
            any(message_text.endswith(ext) for ext in ['.mp4', '.jpg', '.jpeg', '.png', '.gif', '.mp3', '.ogg', '.pdf', '.doc', '.docx']) or
            any(char.isdigit() for char in message_text[:8])):  # Check if starts with timestamp-like pattern
            
            await self.send_media_by_filename(update, message_text)

    async def send_media_by_filename(self, update: Update, filename):
        """Send media file by filename"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Search for exact filename or partial match
            cursor.execute('''
                SELECT saved_filename, file_path, media_type, file_size, caption, user_first_name, save_date
                FROM saved_media 
                WHERE saved_filename = ? OR saved_filename LIKE ?
                ORDER BY save_date DESC
                LIMIT 1
            ''', (filename, f'%{filename}%'))
            
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                # Try to find similar filenames for suggestions
                await self.suggest_similar_files(update, filename)
                return
                
            saved_filename, file_path, media_type, file_size, caption, sender, save_date = result
            
            # Check if file exists
            if not Path(file_path).exists():
                await update.message.reply_text(
                    f"❌ **File not found on disk:** `{saved_filename}`\n"
                    f"The file may have been moved or deleted.",
                    parse_mode='Markdown'
                )
                return
            
            # Send typing action
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id,
                action='upload_document'
            )
            
            # Prepare file info message
            date_obj = datetime.fromisoformat(save_date.replace('Z', '+00:00'))
            info_text = (
                f"📁 **{saved_filename}**\n"
                f"📂 Type: {media_type.title()}\n"
                f"📊 Size: {self.format_file_size(file_size or 0)}\n"
                f"👤 Original Sender: {sender or 'Unknown'}\n"
                f"📅 Saved: {date_obj.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            
            if caption:
                info_text += f"\n💬 Caption: {caption}"
            
            # Send the media file based on its type
            with open(file_path, 'rb') as media_file:
                if media_type == 'photo':
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=media_file,
                        caption=info_text,
                        parse_mode='Markdown'
                    )
                elif media_type == 'video':
                    await context.bot.send_video(
                        chat_id=update.effective_chat.id,
                        video=media_file,
                        caption=info_text,
                        parse_mode='Markdown'
                    )
                elif media_type == 'audio':
                    await context.bot.send_audio(
                        chat_id=update.effective_chat.id,
                        audio=media_file,
                        caption=info_text,
                        parse_mode='Markdown'
                    )
                elif media_type == 'voice':
                    await context.bot.send_voice(
                        chat_id=update.effective_chat.id,
                        voice=media_file,
                        caption=info_text,
                        parse_mode='Markdown'
                    )
                elif media_type == 'video_note':
                    await context.bot.send_video_note(
                        chat_id=update.effective_chat.id,
                        video_note=media_file
                    )
                    # Send info separately for video notes (they don't support captions)
                    await update.message.reply_text(info_text, parse_mode='Markdown')
                elif media_type == 'animation':
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=media_file,
                        caption=info_text,
                        parse_mode='Markdown'
                    )
                else:  # document
                    await context.bot.send_document(
                        chat_id=update.effective_chat.id,
                        document=media_file,
                        caption=info_text,
                        parse_mode='Markdown'
                    )
            
            logger.info(f"Media sent: {saved_filename} to user {update.effective_user.id}")
            
        except Exception as e:
            logger.error(f"Error sending media {filename}: {e}")
            await update.message.reply_text(
                f"❌ **Error sending media:** `{filename}`\n"
                f"Please try again or contact support.",
                parse_mode='Markdown'
            )

    async def suggest_similar_files(self, update: Update, filename):
        """Suggest similar filenames when exact match not found"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Search for similar filenames
            cursor.execute('''
                SELECT saved_filename, media_type, save_date
                FROM saved_media 
                WHERE saved_filename LIKE ?
                ORDER BY save_date DESC
                LIMIT 5
            ''', (f'%{filename}%',))
            
            results = cursor.fetchall()
            conn.close()
            
            if results:
                suggestion_text = f"❌ **File not found:** `{filename}`\n\n"
                suggestion_text += "🔍 **Did you mean:**\n\n"
                
                for saved_filename, media_type, save_date in results:
                    date_obj = datetime.fromisoformat(save_date.replace('Z', '+00:00'))
                    suggestion_text += f"📄 `{saved_filename}`\n"
                    suggestion_text += f"   📂 {media_type.title()} • 📅 {date_obj.strftime('%m/%d %H:%M')}\n\n"
                
                suggestion_text += "💡 **Tip:** Send the exact filename to get the media"
                
                await update.message.reply_text(suggestion_text, parse_mode='Markdown')
            else:
                await update.message.reply_text(
                    f"❌ **File not found:** `{filename}`\n\n"
                    f"💡 Use `/list` to see recent files or `/search <query>` to find media",
                    parse_mode='Markdown'
                )
                
        except Exception as e:
            logger.error(f"Error suggesting files: {e}")
            await update.message.reply_text(
                f"❌ **File not found:** `{filename}`",
                parse_mode='Markdown'
            )

    def extract_media_info(self, message):
        """Extract media information from message"""
        media_info = {
            'user_id': message.from_user.id if message.from_user else None,
            'username': message.from_user.username if message.from_user else None,
            'user_first_name': message.from_user.first_name if message.from_user else None,
            'chat_id': message.chat.id,
            'message_id': message.message_id,
            'caption': message.caption,
            'date': message.date
        }
        
        # Check for different media types
        if message.video:
            media_info.update({
                'media_type': 'video',
                'media_object': message.video,
                'file_id': message.video.file_id,
                'file_size': message.video.file_size,
                'duration': message.video.duration,
                'width': message.video.width,
                'height': message.video.height,
                'mime_type': message.video.mime_type
            })
            
        elif message.photo:
            photo = message.photo[-1]  # Get highest resolution
            media_info.update({
                'media_type': 'photo',
                'media_object': photo,
                'file_id': photo.file_id,
                'file_size': photo.file_size,
                'width': photo.width,
                'height': photo.height
            })
            
        elif message.audio:
            media_info.update({
                'media_type': 'audio',
                'media_object': message.audio,
                'file_id': message.audio.file_id,
                'original_filename': message.audio.file_name,
                'file_size': message.audio.file_size,
                'duration': message.audio.duration,
                'mime_type': message.audio.mime_type
            })
            
        elif message.voice:
            media_info.update({
                'media_type': 'voice',
                'media_object': message.voice,
                'file_id': message.voice.file_id,
                'file_size': message.voice.file_size,
                'duration': message.voice.duration,
                'mime_type': message.voice.mime_type
            })
            
        elif message.video_note:
            media_info.update({
                'media_type': 'video_note',
                'media_object': message.video_note,
                'file_id': message.video_note.file_id,
                'file_size': message.video_note.file_size,
                'duration': message.video_note.duration
            })
            
        elif message.document:
            media_info.update({
                'media_type': 'document',
                'media_object': message.document,
                'file_id': message.document.file_id,
                'original_filename': message.document.file_name,
                'file_size': message.document.file_size,
                'mime_type': message.document.mime_type
            })
            
        elif message.animation:
            media_info.update({
                'media_type': 'animation',
                'media_object': message.animation,
                'file_id': message.animation.file_id,
                'file_size': message.animation.file_size,
                'width': message.animation.width,
                'height': message.animation.height,
                'duration': message.animation.duration,
                'mime_type': message.animation.mime_type
            })
        else:
            return None
            
        return media_info

    async def save_media(self, context, message, media_info):
        """Save media file to storage"""
        try:
            # Get file from Telegram
            file = await context.bot.get_file(media_info['file_id'])
            
            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            if media_info.get('original_filename'):
                # Use original filename
                original_name = Path(media_info['original_filename'])
                filename = f"{timestamp}_{original_name.stem}{original_name.suffix}"
            else:
                # Generate filename based on media type
                extensions = {
                    'video': '.mp4',
                    'photo': '.jpg', 
                    'audio': '.mp3',
                    'voice': '.ogg',
                    'video_note': '.mp4',
                    'document': '',
                    'animation': '.gif'
                }
                ext = extensions.get(media_info['media_type'], '')
                filename = f"{timestamp}_{media_info['file_id'][:8]}{ext}"
            
            # Create file path
            media_type = media_info['media_type']
            file_path = self.media_dirs[media_type] / filename
            
            # Download file
            await file.download_to_drive(file_path)
            
            # Update media info
            media_info['saved_filename'] = filename
            media_info['file_path'] = str(file_path)
            
            logger.info(f"Media saved: {filename}")
            return file_path
            
        except Exception as e:
            logger.error(f"Error saving media: {e}")
            return None

    def save_to_database(self, media_info):
        """Save media information to database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO saved_media (
                    file_id, media_type, original_filename, saved_filename, file_path,
                    file_size, user_id, username, user_first_name, chat_id, message_id,
                    caption, saved_by_user_id, saved_by_username, mime_type,
                    duration, width, height
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                media_info['file_id'],
                media_info['media_type'],
                media_info.get('original_filename'),
                media_info['saved_filename'],
                media_info['file_path'],
                media_info.get('file_size'),
                media_info.get('user_id'),
                media_info.get('username'),
                media_info.get('user_first_name'),
                media_info['chat_id'],
                media_info['message_id'],
                media_info.get('caption'),
                media_info['saved_by_user_id'],
                media_info.get('saved_by_username'),
                media_info.get('mime_type'),
                media_info.get('duration'),
                media_info.get('width'),
                media_info.get('height')
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Database error: {e}")

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show statistics of saved media"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get counts by media type
            cursor.execute('''
                SELECT media_type, COUNT(*), SUM(file_size) 
                FROM saved_media 
                GROUP BY media_type 
                ORDER BY COUNT(*) DESC
            ''')
            
            results = cursor.fetchall()
            
            # Get total count
            cursor.execute('SELECT COUNT(*), SUM(file_size) FROM saved_media')
            total_count, total_size = cursor.fetchone()
            
            conn.close()
            
            if not results:
                await update.message.reply_text("📊 No saved media found!")
                return
                
            stats_text = "📊 **Saved Media Statistics**\n\n"
            
            for media_type, count, size in results:
                size_str = self.format_file_size(size or 0)
                stats_text += f"📁 **{media_type.title()}:** {count} files ({size_str})\n"
            
            stats_text += f"\n📈 **Total:** {total_count} files ({self.format_file_size(total_size or 0)})"
            
            await update.message.reply_text(stats_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Stats error: {e}")
            await update.message.reply_text("❌ Error retrieving statistics")

    async def list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List recent saved media"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT saved_filename, media_type, user_first_name, save_date 
                FROM saved_media 
                ORDER BY save_date DESC 
                LIMIT 10
            ''')
            
            results = cursor.fetchall()
            conn.close()
            
            if not results:
                await update.message.reply_text("📂 No saved media found!")
                return
                
            list_text = "📂 **Recent Saved Media (Last 10)**\n\n"
            
            for filename, media_type, sender, save_date in results:
                # Format date
                date_obj = datetime.fromisoformat(save_date.replace('Z', '+00:00'))
                formatted_date = date_obj.strftime("%m/%d %H:%M")
                
                list_text += f"📄 `{filename}`\n"
                list_text += f"   📂 {media_type.title()} • 👤 {sender or 'Unknown'} • 📅 {formatted_date}\n\n"
            
            list_text += "💡 **Tip:** Send any filename to get the media file"
            
            await update.message.reply_text(list_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"List error: {e}")
            await update.message.reply_text("❌ Error retrieving media list")

    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Search saved media"""
        if not context.args:
            await update.message.reply_text(
                "🔍 **Usage:** `/search <query>`\n"
                "Search in filenames, captions, and sender names",
                parse_mode='Markdown'
            )
            return
            
        query = ' '.join(context.args)
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT saved_filename, media_type, user_first_name, caption, save_date 
                FROM saved_media 
                WHERE saved_filename LIKE ? OR caption LIKE ? OR user_first_name LIKE ?
                ORDER BY save_date DESC
                LIMIT 15
            ''', (f'%{query}%', f'%{query}%', f'%{query}%'))
            
            results = cursor.fetchall()
            conn.close()
            
            if not results:
                await update.message.reply_text(f"🔍 No results found for: `{query}`", parse_mode='Markdown')
                return
                
            search_text = f"🔍 **Search Results for:** `{query}`\n\n"
            
            for filename, media_type, sender, caption, save_date in results:
                date_obj = datetime.fromisoformat(save_date.replace('Z', '+00:00'))
                formatted_date = date_obj.strftime("%m/%d %H:%M")
                
                search_text += f"📄 `{filename}`\n"
                search_text += f"   📂 {media_type.title()} • 👤 {sender or 'Unknown'} • 📅 {formatted_date}\n"
                
                if caption:
                    search_text += f"   💬 {caption[:50]}{'...' if len(caption) > 50 else ''}\n"
                search_text += "\n"
            
            search_text += "💡 **Tip:** Send any filename to get the media file"
            
            await update.message.reply_text(search_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            await update.message.reply_text("❌ Error performing search")

    def format_file_size(self, size_bytes):
        """Format file size in human readable format"""
        if not size_bytes:
            return "0 B"
            
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"

    def run(self):
        """Start the bot"""
        logger.info("Starting Reply Save Bot...")
        logger.info(f"Log Group ID: {LOG_GROUP_ID}")
        print(f"🤖 Bot is running...")
        print(f"📱 Log Group ID: {LOG_GROUP_ID}")
        print(f"💾 Media will be saved to: {self.base_dir}")
        print("🔄 Media retrieval feature enabled")
        print("Press Ctrl+C to stop")
        
        self.application.run_polling()

if __name__ == "__main__":
    print("""
    🔧 Setup Instructions:
    
    1. Replace BOT_TOKEN with your actual bot token
    2. Replace LOG_GROUP_ID with your log group ID
    3. Add bot to your log group as admin
    4. Install dependencies: pip install python-telegram-bot
    5. Run: python reply_save_bot.py
    
    📝 How to get Log Group ID:
    1. Add bot to your group
    2. Send a message in the group
    3. Check bot logs for chat_id (negative number)
    4. Use that ID as LOG_GROUP_ID
    
    💡 Usage:
    1. Send media to log group
    2. Reply to media with /save
    3. Media gets saved automatically
    4. Send filename to retrieve media
    5. Use /get <filename> to retrieve media
    
    🆕 New Features:
    • Send any saved filename to get the media
    • Smart filename suggestions if exact match not found
    • Support for all media types (video, photo, audio, etc.)
    • Automatic media info display when sending files
    """)
    
    # Uncomment to run the bot
    bot = ReplySaveBot()
    bot.run()
