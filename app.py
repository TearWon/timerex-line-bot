from flask import Flask, request, jsonify, session
from linebot import LineBotApi
from linebot.models import TextSendMessage
import logging
import uuid
from datetime import datetime, timedelta
import json

app = Flask(__name__)
app.secret_key = "your_secret_key"  # セッションの暗号化キー

# LINE設定
LINE_ACCESS_TOKEN = "YOUR_LINE_CHANNEL_ACCESS_TOKEN"
LINE_FRIEND_ADD_URL = "https://lin.ee/BhjhlOm"
line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# データ保存（簡易データベースとして辞書を使用）
# 本番環境ではデータベースを使用してください
session_booking_map = {}

# Timerex Webhook
@app.route('/webhook/timerex', methods=['POST'])
def webhook_timerex():
    try:
        # Content-Typeのチェックとデータのパース
        if request.content_type == 'application/json':
            data = request.json
        else:
            raw_data = request.data.decode('utf-8')
            data = json.loads(raw_data)

        logger.info(f"Received data: {data}")

        # Timerex Webhookの処理
        webhook_type = data.get('webhook_type')
        if webhook_type in ['event_confirmed', 'event_cancelled']:
            event = data.get('event')
            if not event:
                logger.error(f"Timerex Webhook received, but 'event' is missing: {data}")
                raise ValueError("'event'キーが存在しません。")

            # 必要なデータを取得
            schedule_time = event.get('local_start_datetime', '不明な日時')

            # online_meeting_providerが文字列か辞書かを判定
            meeting_provider = event.get('online_meeting_provider')
            if isinstance(meeting_provider, dict):  # 辞書の場合
                zoom_url = meeting_provider.get('url', 'URLがありません')
            elif meeting_provider == 'zoom':  # 文字列でZoomが指定されている場合
                zoom_meeting = event.get('zoom_meeting', {})
                zoom_url = zoom_meeting.get('join_url', 'Zoom URLがありません')
            else:
                zoom_url = 'URLがありません'

            # セッションIDの生成と保存
            session_id = str(uuid.uuid4())
            session_booking_map[session_id] = {
                "schedule_time": schedule_time,
                "zoom_url": zoom_url,
                "created_at": datetime.now()
            }
            session['session_id'] = session_id  # セッションに保存
            logger.info(f"予約データを保存しました: {session_booking_map[session_id]}")

            # LINE公式アカウント追加リンクを返す
            return jsonify({'redirect_url': LINE_FRIEND_ADD_URL}), 200

        elif 'events' in data:
            # LINE Webhook形式の場合
            logger.info(f"LINE Webhook received: {data.get('events')}")
            return jsonify({'status': 'success', 'message': 'LINE Webhook data processed'}), 200

        # 想定外のデータ構造
        else:
            logger.error(f"Unexpected data structure: {data}")
            raise ValueError("データ構造がTimerexおよびLINEの仕様に一致しません。")

    except json.JSONDecodeError as e:
        logger.error(f"JSONパースエラー: {e}")
        return jsonify({'status': 'error', 'message': 'Invalid JSON format'}), 400
    except ValueError as e:
        logger.error(f"ValueError: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify({'status': 'error', 'message': 'Internal Server Error'}), 500


# LINE Webhook（友だち追加後の処理）
@app.route('/webhook/line', methods=['POST'])
def line_webhook():
    try:
        body = request.json
        events = body.get('events', [])

        for event in events:
            if event['type'] == 'follow':  # 友だち追加時のイベント
                user_id = event['source']['userId']

                # セッションIDを取得
                session_id = session.get('session_id')
                logger.info(f"友だち追加: LINE User ID: {user_id}, セッションID: {session_id}")

                if not session_id:
                    logger.error("セッションIDが見つかりません。")
                    return jsonify({'status': 'error', 'message': 'セッションIDがありません。'}), 400

                # セッションIDを使用して予約データを検索
                booking_data = find_booking_by_session(session_id)

                if booking_data:
                    # 予約内容をLINEで通知
                    send_booking_details_to_line(user_id, booking_data)
                else:
                    logger.warning(f"予約データが見つかりません: セッションID: {session_id}")

        return jsonify({'status': 'success'}), 200

    except Exception as e:
        logger.error(f"Error processing LINE webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ユーティリティ関数: セッションIDで予約データを検索
def find_booking_by_session(session_id):
    booking_data = session_booking_map.get(session_id)

    # データが見つかった場合、期限切れか確認
    if booking_data:
        created_at = booking_data['created_at']
        if datetime.now() - created_at < timedelta(hours=1):  # 1時間以内のデータのみ有効
            return booking_data
        else:
            logger.info(f"予約データが期限切れです: セッションID: {session_id}")
            del session_booking_map[session_id]  # 古いデータを削除
    return None


# ユーティリティ関数: LINEユーザーに予約データを送信
def send_booking_details_to_line(user_id, booking_data):
    try:
        schedule_time = booking_data['schedule_time']
        zoom_url = booking_data['zoom_url']

        message = f"予約が確定しました！\n\n日時: {schedule_time}\nZoomURL: {zoom_url}"
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=message)
        )
        logger.info(f"予約情報をLINEに通知しました: {user_id}")
    except Exception as e:
        logger.error(f"LINE通知に失敗しました: {e}")


# テスト用エンドポイント（動作確認用）
@app.route('/')
def home():
    return "TimeRex LINE Integration with Session ID is running!"


if __name__ == '__main__':
    app.run(debug=True, port=5000)