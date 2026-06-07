from futu import *
import gc
import queue
import logging

logger = logging.getLogger(__name__)

class FutuTickListener(TickerHandlerBase):
    def __init__(self, data_queue):
        super(FutuTickListener, self).__init__()
        self.queue = data_queue # 注入线程共享安全队列
        self.tick_count = 0

    def on_recv_rsp(self, rsp_pb):
        ret_code, content = super(FutuTickListener, self).on_recv_rsp(rsp_pb)
        if ret_code != RET_OK:
            return RET_ERROR, content

        # 生产者：只解析，不计算，极速打入队列
        for _, row in content.iterrows():
            tick_packet = {
                "code": row['code'],
                "price": float(row['price']),
                "volume": int(row['volume']),
                "turnover": float(row['turnover']) if 'turnover' in row else float(row['price']*row['volume']),
                "ticker_direction": str(row['ticker_direction']),
                "bid_price": float(row['bid_price']) if 'bid_price' in row else 0.0,
                "ask_price": float(row['ask_price']) if 'ask_price' in row else 0.0
            }
            try:
                # 🔥 防止无限阻塞导致富途线程卡死，增加 timeout 和 Full 异常处理
                self.queue.put(tick_packet, block=True, timeout=2.0)
            except queue.Full:
                logger.error(f"🚨 队列已满(100k)，消费者卡死或落后，丢弃数据: {row['code']}")
        
        # 🔥 定期垃圾回收（每10000条消息触发一次）
        self.tick_count += len(content)
        if self.tick_count % 10000 == 0:
            gc.collect()
        
        return RET_OK, content