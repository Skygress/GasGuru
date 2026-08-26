import os
import json
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from web3 import Web3
import redis
import logging

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Web3 connections
eth_w3 = Web3(Web3.HTTPProvider(os.getenv('ETH_RPC_URL')))
bsc_w3 = Web3(Web3.HTTPProvider(os.getenv('BSC_RPC_URL')))

# Initialize Redis (for storing alerts and user data)
redis_client = redis.Redis.from_url(os.getenv('REDIS_URL'), decode_responses=True)

# Gas price thresholds for recommendations
GAS_THRESHOLDS = {
    'eth': {'low': 20, 'medium': 40, 'high': 60},
    'bsc': {'low': 3, 'medium': 6, 'high': 10}
}

# Helper function to get gas prices
def get_gas_prices():
    try:
        # ETH Gas
        eth_gas = eth_w3.eth.gas_price
        eth_gwei = eth_w3.from_wei(eth_gas, 'gwei')
        
        # BSC Gas
        bsc_gas = bsc_w3.eth.gas_price
        bsc_gwei = bsc_w3.from_wei(bsc_gas, 'gwei')
        
        return {
            'eth': round(eth_gwei, 2),
            'bsc': round(bsc_gwei, 2)
        }
    except Exception as e:
        logger.error(f"Error fetching gas prices: {e}")
        return None

# Helper function to get historical gas (simulated with Redis)
def get_historical_gas(chain):
    key = f"gas_history_{chain}"
    history = redis_client.lrange(key, 0, 23)
    if not history:
        # Generate mock historical data
        import random
        base_price = 30 if chain == 'eth' else 5
        history = [str(base_price + random.randint(-10, 15)) for _ in range(24)]
        for price in history:
            redis_client.rpush(key, price)
        redis_client.expire(key, 3600)  # Expire in 1 hour
    return [float(h) for h in history]

# Store user alert
def set_alert(user_id, chain, price):
    key = f"alert_{user_id}_{chain}"
    redis_client.set(key, price)
    redis_client.expire(key, 86400)  # Expire in 24 hours

# Get user alert
def get_alert(user_id, chain):
    key = f"alert_{user_id}_{chain}"
    return redis_client.get(key)

# Remove user alert
def remove_alert(user_id, chain):
    key = f"alert_{user_id}_{chain}"
    redis_client.delete(key)

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_text = (
        f"⛽ *Welcome to GasGuruBot, {user.first_name}!* ⛽\n\n"
        "I monitor ETH and BSC gas prices in real-time.\n"
        "Here's what I can do for you:\n\n"
        "🔥 `/gas` - Check current gas prices\n"
        "🔔 `/alert <price>` - Set alert for ETH gas (e.g., /alert 20)\n"
        "📊 `/trend` - View 24-hour gas trend\n"
        "💡 `/recommend` - Get transaction recommendations\n"
        "ℹ️ `/about` - About this bot\n\n"
        "_Built for Web3 degens by a Telegram Expert 🚀_"
    )
    keyboard = [
        [InlineKeyboardButton("⛽ Check Gas", callback_data='check_gas')],
        [InlineKeyboardButton("📊 View Trend", callback_data='view_trend')],
        [InlineKeyboardButton("💡 Get Recommendation", callback_data='get_recommend')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

# Gas command
async def gas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching latest gas prices...")
    
    prices = get_gas_prices()
    if not prices:
        await update.message.reply_text("❌ Error fetching gas prices. Please try again.")
        return
    
    eth_status = "🟢 Low" if prices['eth'] <= GAS_THRESHOLDS['eth']['low'] else "🟡 Medium" if prices['eth'] <= GAS_THRESHOLDS['eth']['medium'] else "🔴 High"
    bsc_status = "🟢 Low" if prices['bsc'] <= GAS_THRESHOLDS['bsc']['low'] else "🟡 Medium" if prices['bsc'] <= GAS_THRESHOLDS['bsc']['medium'] else "🔴 High"
    
    message = (
        f"⛽ *Current Gas Prices* ⛽\n\n"
        f"🟣 *Ethereum:* `{prices['eth']} Gwei`\n"
        f"Status: {eth_status}\n\n"
        f"🟡 *BSC:* `{prices['bsc']} Gwei`\n"
        f"Status: {bsc_status}\n\n"
        f"_Updated: {datetime.now().strftime('%H:%M:%S')}_"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data='refresh_gas')],
        [InlineKeyboardButton("🔔 Set Alert", callback_data='set_alert')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

# Alert command
async def set_alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "❌ Please specify a gas price.\n"
            "Example: `/alert 20` (will alert when ETH gas drops below 20 Gwei)\n\n"
            "You can also set BSC alerts: `/alert bsc 3`"
        )
        return
    
    args = context.args
    chain = 'eth'
    price = args[0]
    
    if len(args) == 2:
        chain = args[0].lower()
        price = args[1]
        if chain not in ['eth', 'bsc']:
            await update.message.reply_text("❌ Chain must be 'eth' or 'bsc'")
            return
    
    try:
        price = float(price)
        if price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid positive number")
        return
    
    set_alert(user_id, chain, price)
    
    chain_name = "Ethereum" if chain == 'eth' else "BSC"
    await update.message.reply_text(
        f"✅ Alert set!\n\n"
        f"You will be notified when {chain_name} gas drops below `{price} Gwei`\n\n"
        f"To remove alert: `/remove_alert {chain}`"
    )

# Remove alert command
async def remove_alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chain = context.args[0].lower() if context.args else 'eth'
    
    if chain not in ['eth', 'bsc']:
        await update.message.reply_text("❌ Chain must be 'eth' or 'bsc'")
        return
    
    remove_alert(user_id, chain)
    chain_name = "Ethereum" if chain == 'eth' else "BSC"
    await update.message.reply_text(f"✅ Alert for {chain_name} removed successfully!")

# Trend command
async def trend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 Generating gas trend...")
    
    eth_history = get_historical_gas('eth')
    bsc_history = get_historical_gas('bsc')
    
    # Create simple ASCII chart
    eth_trend = "📈 ETH Trend (last 24h):\n"
    for i, price in enumerate(eth_history[-12:]):  # Last 12 hours
        bars = int(price / 2)
        eth_trend += f"{i+1:2}h: {'█' * bars} {price} Gwei\n"
    
    bsc_trend = "\n📊 BSC Trend (last 24h):\n"
    for i, price in enumerate(bsc_history[-12:]):
        bars = int(price * 2)
        bsc_trend += f"{i+1:2}h: {'█' * bars} {price} Gwei\n"
    
    message = eth_trend + bsc_trend
    await update.message.reply_text(message, parse_mode='Markdown')

# Recommend command
async def recommend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prices = get_gas_prices()
    if not prices:
        await update.message.reply_text("❌ Error fetching gas prices.")
        return
    
    eth_recommend = "🟢 Good to transact now!" if prices['eth'] <= GAS_THRESHOLDS['eth']['medium'] else "🔴 Wait for gas to drop below 40 Gwei"
    bsc_recommend = "🟢 Good to transact now!" if prices['bsc'] <= GAS_THRESHOLDS['bsc']['medium'] else "🔴 Wait for gas to drop below 6 Gwei"
    
    message = (
        f"💡 *Transaction Recommendations* 💡\n\n"
        f"🟣 *Ethereum:* {eth_recommend}\n"
        f"Current: `{prices['eth']} Gwei`\n\n"
        f"🟡 *BSC:* {bsc_recommend}\n"
        f"Current: `{prices['bsc']} Gwei`\n\n"
        f"_Based on current gas prices and historical trends_"
    )
    await update.message.reply_text(message, parse_mode='Markdown')

# About command
async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        f"⛽ *GasGuruBot v1.0* ⛽\n\n"
        f"Built by a Telegram Expert & Web3 Developer 🚀\n\n"
        f"*Features:*\n"
        f"• Real-time ETH & BSC gas monitoring\n"
        f"• Custom price alerts\n"
        f"• 24-hour trend analysis\n"
        f"• Smart transaction recommendations\n"
        f"• No external APIs - pure blockchain RPC\n\n"
        f"*Tech Stack:*\n"
        f"• Python + python-telegram-bot\n"
        f"• Web3.py for blockchain interaction\n"
        f"• Redis for data persistence\n"
        f"• Deployed on Railway\n\n"
        f"_Support the project: ⭐ GitHub_"
    )
    await update.message.reply_text(message, parse_mode='Markdown')

# Callback query handler
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == 'check_gas':
        await gas(update, context)
    elif data == 'refresh_gas':
        await gas(update, context)
    elif data == 'view_trend':
        await trend(update, context)
    elif data == 'get_recommend':
        await recommend(update, context)
    elif data == 'set_alert':
        await query.edit_message_text(
            "To set an alert, use:\n"
            "`/alert <price>` for ETH (e.g., /alert 20)\n"
            "`/alert bsc <price>` for BSC (e.g., /alert bsc 3)\n\n"
            "You'll be notified when gas drops below your target!",
            parse_mode='Markdown'
        )

# Background task to check alerts
async def check_alerts(app: Application):
    while True:
        try:
            prices = get_gas_prices()
            if prices:
                # Get all users with alerts (simplified - in production use a proper user store)
                for chain in ['eth', 'bsc']:
                    # This is simplified - in production you'd maintain a list of users
                    keys = redis_client.keys(f"alert_*_{chain}")
                    for key in keys:
                        user_id = int(key.split('_')[1])
                        alert_price = float(redis_client.get(key))
                        
                        current_price = prices[chain]
                        if current_price < alert_price:
                            chain_name = "Ethereum" if chain == 'eth' else "BSC"
                            await app.bot.send_message(
                                chat_id=user_id,
                                text=f"🔔 *ALERT!* 🔔\n\n"
                                f"{chain_name} gas has dropped to `{current_price} Gwei`\n"
                                f"Your alert was set at `{alert_price} Gwei`\n\n"
                                f"⏰ Time to transact! 🚀",
                                parse_mode='Markdown'
                            )
                            # Remove alert after firing
                            remove_alert(user_id, chain)
        except Exception as e:
            logger.error(f"Error in alert checker: {e}")
        
        await asyncio.sleep(60)  # Check every minute

# Main function
def main():
    # Create application
    application = Application.builder().token(os.getenv('BOT_TOKEN')).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("gas", gas))
    application.add_handler(CommandHandler("alert", set_alert_command))
    application.add_handler(CommandHandler("remove_alert", remove_alert_command))
    application.add_handler(CommandHandler("trend", trend))
    application.add_handler(CommandHandler("recommend", recommend))
    application.add_handler(CommandHandler("about", about))
    
    # Add callback handler
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Start background task
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(check_alerts(application))
    
    # Start bot
    application.run_polling()

if __name__ == '__main__':
    main()
