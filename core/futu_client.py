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
                "_type": "ticker",
                "code": row['code'],
                "name": str(row['name']) if 'name' in row else '',
                "time": str(row['time']) if 'time' in row else '',
                "price": float(row['price']),
                "volume": int(row['volume']) if 'volume' in row else 0,
                "turnover": float(row['turnover']) if 'turnover' in row else float(row['price']*row['volume']),
                "ticker_direction": str(row['ticker_direction']) if 'ticker_direction' in row else 'NEUTRAL',
                "sequence": int(row['sequence']) if 'sequence' in row else 0,
                "type": str(row['type']) if 'type' in row else '',
                "push_data_type": str(row['push_data_type']) if 'push_data_type' in row else '',
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


class FutuOrderBookListener(OrderBookHandlerBase):
    def __init__(self, data_queue):
        super(FutuOrderBookListener, self).__init__()
        self.queue = data_queue # 注入线程共享安全队列
        self.ob_count = 0

    def on_recv_rsp(self, rsp_pb):
        ret_code, content = super(FutuOrderBookListener, self).on_recv_rsp(rsp_pb)
        if ret_code != RET_OK:
            return RET_ERROR, content

        # content 是个字典，包含 code, name, svr_recv_time_bid, svr_recv_time_ask, Bid, Ask
        ask_list = content.get('Ask', [])
        bid_list = content.get('Bid', [])
        
        # 转换为数组，供 ClickHouse 存储 (排除 order_detail 散单字典)
        ask_prices = [float(x[0]) for x in ask_list]
        ask_volumes = [int(x[1]) for x in ask_list]
        ask_orders = [int(x[2]) for x in ask_list]
        
        bid_prices = [float(x[0]) for x in bid_list]
        bid_volumes = [int(x[1]) for x in bid_list]
        bid_orders = [int(x[2]) for x in bid_list]
        
        # 构造扁平化 packet，并填入 _type
        ob_packet = {
            "_type": "order_book",
            "code": content.get('code', ''),
            "name": content.get('name', ''),
            "svr_recv_time_bid": content.get('svr_recv_time_bid', ''),
            "svr_recv_time_ask": content.get('svr_recv_time_ask', ''),
            "ask_prices": ask_prices,
            "ask_volumes": ask_volumes,
            "ask_orders": ask_orders,
            "bid_prices": bid_prices,
            "bid_volumes": bid_volumes,
            "bid_orders": bid_orders
        }
        
        try:
            # 防止阻塞富途线程，增加 timeout
            self.queue.put(ob_packet, block=True, timeout=2.0)
        except queue.Full:
            logger.error(f"🚨 队列已满(100k)，丢弃盘口数据: {ob_packet['code']}")
            
        self.ob_count += 1
        if self.ob_count % 5000 == 0:
            gc.collect()
            
        return RET_OK, content