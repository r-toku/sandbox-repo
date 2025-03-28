import json
import logging
import boto3
# from datetime import date, datetime
import datetime
import threading

def init_logging(log_level=logging.WARNING):
  # logger の初期化

  class JsonFormatter(logging.Formatter):
    # logger の出力形式を設定するクラス

    def json_serial(self, obj):
      # 日付型は dump できないので置換
      if isinstance(obj, (datetime.datetime, datetime.date)):
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
        if aws_request_id:
            record_dict['aws_request_id'] = aws_request_id

        if record.exc_info:
          # 例外が発生した場合は、例外情報を追加
          # https://qiita.com/hoto17296/items/fa840823245fa4e7517d
          record_dict['exc_traceback'] = self.formatException(record.exc_info).splitlines()

        extra_fields = ['data']

        # extra に入れられたデータを格納する。改善の余地あり。
        # https://dev.classmethod.jp/articles/python-logger-kwarg-extra/
        for field in extra_fields:
          value = getattr(record, field, None)
          if value is not None:
            record_dict[field] = value

        return json.dumps(record_dict, ensure_ascii=False, default=self.json_serial)

      except:
        raise

  # -- ロガーの設定 ----
  # http://qiita.com/smats-rd/items/c5f4345aca3a452041c7#しかし勿論こんなことをしてはいけない
  # https://qiita.com/smats-rd/items/c5f4345aca3a452041c7#%E3%81%97%E3%81%8B%E3%81%97%E5%8B%BF%E8%AB%96%E3%81%93%E3%82%93%E3%81%AA%E3%81%93%E3%81%A8%E3%82%92%E3%81%97%E3%81%A6%E3%81%AF%E3%81%84%E3%81%91%E3%81%AA%E3%81%84
  # ハンドラがあればスキップ
  if not logger.handlers:
    logger.propagate = False                # ルートロガーへの伝搬を禁止
    logger.setLevel(log_level)              # ログレベルの設定
    handler = logging.StreamHandler()       # ハンドラの設定
    handler.setLevel(log_level)             # ハンドラのログレベルを設定
    handler.setFormatter(JsonFormatter())   # カスタムフォーマッタをハンドラに設定
    logger.addHandler(handler)              # ハンドラの追加
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
# thread_local = threading.local()
aws_request_id = None

# -- logger ----
logger = logging.getLogger(__name__)  # ロガーを設定
init_logging(logging.DEBUG)           # logger の初期化

# -- boto3 client ----
s3_client = boto3.client('s3')

def lambda_handler(event, context):
  # thread_local.aws_request_id = context.aws_request_id
  global aws_request_id
  aws_request_id = context.aws_request_id

  try:
    0/0
  except Exception as e:
    logger.warning('計算できません。', exc_info=True)

  # except がない箇所でエラーになった場合どうするか考える。
  # 0/0

  list_bucket()
  print(vars(context))
  print('context type:', type(context))
  print('context aws_request_id', context.aws_request_id)
  logger.debug('context', extra={'data': context})

  return {
    'statusCode': 200,
    'body': json.dumps('Hello from Lambda!')
  }
