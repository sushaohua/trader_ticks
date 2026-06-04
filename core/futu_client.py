from futu import *

class FutuTickListener(TickerHandlerBase):
    def __init__(self, data_queue):
        super(FutuTickListener, self).__init__()
        self.queue = data_queue # 注入线程共享安全队列

    def on_recv_rsp(self, rsp_pb):
        ret_code, content = super(FutuTickListener, self).on_receive_form(rsp_pb)
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
            self.queue.put(tick_packet)
        return RET_OK, content