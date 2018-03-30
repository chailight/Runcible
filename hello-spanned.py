#! /usr/bin/env python3

import asyncio
import monome
import virtualgrid

class Hello(monome.App):
    def on_grid_ready(self):
        print("connected to ", self.grid.id)

    def on_grid_key(self, x, y, s):
        self.grid.led_set(x, y, s)

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    hello_app = Hello()
    asyncio.async(virtualgrid.SpanningSerialOsc.create(loop=loop, autoconnect_app=hello_app))
    loop.run_forever()
