#! /usr/bin/env python3

import asyncio
import aiosc
import monome
import itertools

class Gate(aiosc.OSCProtocol):
    def __init__(self, prefix, bridge):
        self.prefix = prefix.strip('/')
        self.bridge = bridge
        #print(self.prefix)
        print('{}'.format(self.prefix))

        super().__init__(handlers={
            '/{}/grid/led/set'.format(self.prefix):
                lambda addr, path, x, y, s:
                    self.bridge.led_set(int(x), int(y), int(s)),
            '/{}/grid/led/all'.format(self.prefix):
                lambda addr, path, s:
                    self.bridge.led_all(int(s)),
            '/{}/grid/led/map'.format(self.prefix):
                lambda addr, path, x_offset, y_offset, *s:
                    self.bridge.led_map(x_offset, y_offset, list(itertools.chain([monome.unpack_row(r) for r in s]))),
                    #self.bridge.led_map(x_offset, y_offset, s),
            '/{}/grid/led/row'.format(self.prefix):
                lambda addr, path, x_offset, y, *s:
                    self.bridge.led_row(x_offset, y, list(itertools.chain(*[monome.unpack_row(r) for r in s]))),
            '/{}/grid/led/col'.format(self.prefix):
                lambda addr, path, x, y_offset, *s:
                    self.bridge.led_col(x, y_offset, list(itertools.chain(*[monome.unpack_row(r) for r in s]))),
            '/{}/grid/led/intensity'.format(self.prefix):
                lambda addr, path, i:
                    self.bridge.led_intensity(i),
            '/{}/tilt/set'.format(self.prefix):
                lambda addr, path, n, s:
                    self.bridge.tilt_set(n, s),
            '//*': self.echo,
        })

    def echo(self, addr, path, *args):
        pass
        #print("incoming message from {}: {} {}".format(addr, path, args))
        # echo the message
        #self.send(path, *args, addr=addr)

    def grid_key(self, x, y, s):
        #self.send('/{}/grid/key'.format(self.prefix), x, y, s, addr=(self.bridge.app_host, self.bridge.app_port))
        #aiosc.send(('127.0.0.1', 3333), '/hello', 'world')
        path = '/{}/grid/key'.format(self.prefix)
        args = str(x+1) + ' ' + str(y) + ' ' + str(s)
        #print(self.bridge.id,path, args, self.bridge.app_port)

class Grid(monome.Monome):
    def __init__(self, app_host = '127.0.0.1', app_port = 8000, loop=None):
        super().__init__('/hello')
        self.app_host = app_host
        self.app_port = app_port
        if loop is None:
            loop = asyncio.get_event_loop()
        self.loop = loop

    def ready(self):
        asyncio.async(self.init_gate())

    @asyncio.coroutine
    def init_gate(self):
        transport, protocol = yield from self.loop.create_datagram_endpoint(
            lambda: Gate(self.id, self),
            local_addr=(self.app_host,self.app_port),
        )
        self.gate = protocol

    #@asyncio.coroutine
    def grid_key(self, x, y, s):
        #self.led_set(x, y, s)
        path = '/{}/grid/key'.format(self.id)
        #args = str(x) + ' ' + str(y) + ' ' + str(s)
        asyncio.async(aiosc.send(('127.0.0.1', 9000), path, x, y, s))

class Grid2(monome.Monome):
    def __init__(self):
        super().__init__('/hello')
        self.app_port = 8001 
    
    #@asyncio.coroutine
    def grid_key(self, x, y, s):
        #self.led_set(x, y, s)
        path = '/{}/grid/key'.format(self.id)
        #args = str(x) + ' ' + str(y) + ' ' + str(s)
        asyncio.async(aiosc.send(('127.0.0.1', 9000), path, x, y, s))

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    g1 = lambda: Grid(app_port = 8000) 
    g2 = lambda: Grid(app_port = 8001) 
    coro = asyncio.async(monome.create_serialosc_connection({
        'm40h-001': g1,
        'm40h-002': g2,
    }, loop=loop))

    #coro2 = asyncio.async(monome.create_serialosc_connection(Grid2, loop=loop))
    loop.run_until_complete(coro)
    #loop.run_until_complete(coro2)
    loop.run_forever()
