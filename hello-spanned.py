#! /usr/bin/env python3

import asyncio
import monome
import virtualgrid
import numpy as np

class Hello(monome.App):
    def __init__(self):
        super().__init__()
        self.chaser = 0
        self.current_pos = 0

    def on_grid_ready(self):
        self.my_buffer = virtualgrid.myGridBuffer(self.grid.width,self.grid.height)
        #self.my_pos_buffer = virtualgrid.myGridBuffer(self.grid.width,self.grid.height)
        #self.my_pos_buffer.led_set(0,7,1)
        self.my_pos_buffer = np.array([[1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]])
        asyncio.async(self.draw())


    async def stop_chaser(self):
        self.chaser = 0
        print ("chaser",self.chaser)

    async def start_chaser(self):
        self.chaser = 1
        print ("chaser",self.chaser)
        await self.run_chaser()

    async def draw(self):
        #print(self.current_pos)
        while (True):
            self.grid.led_map(0,0,self.my_buffer.levels)
            await asyncio.sleep(0.1)

    async def run_chaser(self):
        while (self.chaser == 1) :
            print(self.current_pos)
            #print("pos_buffer",np.roll((self.my_pos_buffer).astype(int),self.current_pos,axis=1))
            #print("buffer",(self.my_buffer.levels/15).astype(int))
            #self.my_pos_buffer = np.roll((self.my_pos_buffer).astype(int),1,axis=1)
            print(self.my_pos_buffer)
            print(self.my_pos_buffer.shape)
            print(np.split(self.my_buffer.levels,[7],axis=1)[0])
            print(np.split(self.my_buffer.levels,[7],axis=1)[0].shape)
            self.my_buffer.led_map(0,0,(np.concatenate((np.asarray(np.split(self.my_buffer.levels,[7],axis=1)[0]),np.roll((self.my_pos_buffer).astype(int),self.current_pos,axis=1).T,),axis=1)))
            #np.roll(self.my_pos_buffer,1)
            self.current_pos = (self.current_pos + 1)%16
            #self.my_buffer.led_set(self.current_pos-1,7,0)
            #self.my_buffer.led_set(self.current_pos,7,1)
            await asyncio.sleep(1)


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

        clear_all = [[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]]

        self.my_buffer.led_set(x, y, s)

        if x==0 and y==0:
            self.my_buffer.led_set(0,0,s)
            self.my_buffer.led_set(1,0,s)
            self.my_buffer.led_set(2,0,s)
            self.my_buffer.led_set(3,0,s)
            self.my_buffer.led_set(4,0,s)
            self.my_buffer.led_set(5,0,s)
            self.my_buffer.led_set(6,0,s)
            self.my_buffer.led_set(7,0,s)
            self.my_buffer.led_set(8,0,s)
            self.my_buffer.led_set(9,0,s)
            self.my_buffer.led_set(10,0,s)
            self.my_buffer.led_set(11,0,s)
            self.my_buffer.led_set(12,0,s)
            self.my_buffer.led_set(13,0,s)
            self.my_buffer.led_set(14,0,s)
            self.my_buffer.led_set(15,0,s)

        #if x==0 and y==1:
            #self.my_buffer.led_map(0,0,np.asarray(data1))

        #if x==0 and y==2:
        #    self.my_buffer.led_map(0,0,np.asarray(data2))

        if x==0 and y==3:
            self.my_buffer.led_map(0,0,np.asarray(clear_all).T)

        if x==0 and y==4:
            print("data 3")
            self.my_buffer.led_map(0,0,np.asarray(data3).T)

        if x==0 and y==5:
            print("data 4")
            self.my_buffer.led_row(0,0,np.asarray(data4).T)

        if x==0 and y==6:
            print("data 5")
            self.my_buffer.led_map(0,0,np.asarray(data5).T)

        if x==1 and y==0 and s == 1:
            asyncio.async(self.start_chaser())

        if x==2 and y==0 and s == 1:
            asyncio.async(self.stop_chaser())



if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    hello_app = Hello()
    asyncio.async(virtualgrid.SpanningSerialOsc.create(loop=loop, autoconnect_app=hello_app))
    loop.run_forever()
