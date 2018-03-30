#! /usr/bin/env python3

import asyncio
import monome
import virtualgrid

class Hello(monome.App):
    def __init__(self):
        super().__init__()
        self.chaser = 0
        self.current_pos = 0

    #def on_grid_ready(self):
        #print("connected to ", self.grid.id)
        #pass

    async def stop_chaser(self):
        self.chaser = 0
        print ("chaser",self.chaser)

    async def start_chaser(self):
        self.chaser = 1
        print ("chaser",self.chaser)
        await self.run_chaser()

    async def run_chaser(self):
        while (self.chaser == 1) :
            print(self.current_pos)
            self.current_pos = (self.current_pos + 1)%16
            await asyncio.sleep(10)


    def on_grid_key(self, x, y, s):
        print(x,y)
        data1 = [[1,1,1,1,1,1,1,1],
                [0,0,0,0,0,0,0,0],
                [1,1,1,1,1,1,1,1],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0]]

        data2 = [[0,0,0,0,0,0,0,0],
                [1,1,1,1,1,1,1,1],
                [0,0,0,0,0,0,0,0],
                [1,1,1,1,1,1,1,1],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0]]

        data3 = [[0,1,0,1,0,1,0,1,0,0,1,0,0,1,0,0],
                [1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1],
                [1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]]

        data4 = [0,1,0,1,0,1,0,1,0,0,1,0,0,1,0,0]

        data5 = [[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], 
                [15, 0, 0, 15, 0, 0, 0, 15, 0, 0, 15, 0, 0, 15, 15, 0], 
                [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], 
                [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], 
                [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], 
                [15, 15, 15, 15, 0, 0, 15, 0, 0, 0, 0, 0, 0, 0, 0, 0], 
                [15, 15, 15, 15, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], 
                [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]]

        clear_all = [[0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0]]

        self.grid.led_set(x, y, s)

        if x==0 and y==0:
            self.grid.led_set(0,0,s)
            self.grid.led_set(1,0,s)
            self.grid.led_set(2,0,s)
            self.grid.led_set(3,0,s)
            self.grid.led_set(4,0,s)
            self.grid.led_set(5,0,s)
            self.grid.led_set(6,0,s)
            self.grid.led_set(7,0,s)
            self.grid.led_set(8,0,s)
            self.grid.led_set(9,0,s)
            self.grid.led_set(10,0,s)
            self.grid.led_set(11,0,s)
            self.grid.led_set(12,0,s)
            self.grid.led_set(13,0,s)
            self.grid.led_set(14,0,s)
            self.grid.led_set(15,0,s)

        if x==0 and y==1:
            self.grid.led_map(0,0,data1)

        if x==0 and y==2:
            self.grid.led_map(0,0,data2)

        if x==0 and y==3:
            self.grid.led_map(0,0,clear_all)

        if x==0 and y==4:
            self.grid.led_map(0,0,data3)

        if x==0 and y==5:
            self.grid.led_row(0,0,data4)

        if x==0 and y==6:
            self.grid.led_map(0,0,data5)

        if x==1 and y==0 and s == 1:
            asyncio.async(self.start_chaser())

        if x==2 and y==0 and s == 1:
            asyncio.async(self.stop_chaser())



if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    hello_app = Hello()
    asyncio.async(virtualgrid.SpanningSerialOsc.create(loop=loop, autoconnect_app=hello_app))
    loop.run_forever()
