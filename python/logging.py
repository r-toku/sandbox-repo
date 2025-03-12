import json
import logging
import boto3
from datetime import date, datetime
import threading

def init_logging(log_level=logging.WARNING):
  # logger の初期化

  # リクエスト ID を追加するフィルタ
  class RequestIdFilter(logging.Filter):
      def filter(self, record):
          record.aws_request_id = getattr(thread_local, 'aws_request_id', None)
          return True

  class JsonFormatter(logging.Formatter):
    # logger の出力形式を設定するクラス

    def json_serial(self, obj):
      # 日付型は dump できないので置換
      if isinstance(obj, (datetime, date)):
        return obj.isoformat()
      else:
        return str(obj)

    def format(self, record):
      try:
        # record_dict = vars(record)
        record_dict = {
          'timestamp': self.formatTime(record, self.datefmt),
          'name': record.name,
          'level': record.levelname,
          'message': record.getMessage(),
        }
        # リクエスト ID を追加
        if getattr(record, 'aws_request_id', None):
            record_dict['aws_request_id'] = record.aws_request_id

        extra_fields = ['data']

        for field in extra_fields:
          value = getattr(record, field, None)
          if value is not None:
            record_dict[field] = value
        return json.dumps(record_dict, ensure_ascii=False, default=self.json_serial)

      except:
        raise

  # -- ロガーの設定 ----
  # ハンドラがあればスキップ
  if not logger.handlers:
    logger.propagate = False                # ルートロガーへの伝搬を禁止
    logger.setLevel(log_level)              # ログレベルの設定
    handler = logging.StreamHandler()       # ハンドラの設定
    handler.setLevel(log_level)             # ハンドラのログレベルを設定
    handler.setFormatter(JsonFormatter())   # カスタムフォーマッタをハンドラに設定
    logger.addHandler(handler)              # ハンドラの追加
    logger.addFilter(RequestIdFilter())     # グローバルフィルタを追加して、どこからのログもリクエスト ID を含める
    logger.debug('Logging is initialized')

def list_bucket():
  response = {} 
  try:
    response = s3_client.list_buckets().get('Buckets', {})
    logger.debug('list_bucket response', extra={'data': response})
  except:
    pass

  return response

# -- スレッドローカル変数 宣言 ----
thread_local = threading.local()

# -- logger ----
logger = logging.getLogger(__name__)  # ロガーを設定
init_logging(logging.DEBUG)           # logger の初期化

# -- boto3 client ----
s3_client = boto3.client('s3')

def lambda_handler(event, context):
  thread_local.aws_request_id = context.aws_request_id

  list_bucket()
  print(vars(context))
  print('context type:', type(context))
  print('context aws_request_id', context.aws_request_id)
  logger.debug('context', extra={'data': context})

  return {
    'statusCode': 200,
    'body': json.dumps('Hello from Lambda!')
  }
