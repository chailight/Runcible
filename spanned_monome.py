# pymonome plus - add on for Artem Popov's pymonome 
#
# spanning modifications by Mark Pedersen <markp@chailight.com>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import asyncio
import aiosc
import itertools
import re
import monome


DEFAULT_APP_HOST = '127.0.0.1'
DEFAULT_APP_PORT = 8000
DEFAULT_APP_PREFIX = '/monome'


class Virtual(aiosc.OSCProtocol):
    def __init__(self, id, xsize, ysize, port=0):
        #OSCServer.__init__(self, ('', port))
        self.id = id
        self.width = xsize
        self.height = ysize
        self.rotation = None
        self.varibright = False 
        self.app_host = DEFAULT_APP_HOST
        self.app_port = DEFAULT_APP_PORT
        self.prefix = DEFAULT_APP_PREFIX

        super().__init__(handlers={
            '/sys/disconnect': lambda *args: self.disconnect,
            #'/sys/connect': lambda *args: self.connect,
            #'/sys/{id,size,host,port,prefix,rotation}': self.sys_info,
            '//*': self.echo,
            #'/{}/grid/key'.format(self.prefix): lambda addr, path, x, y, s: self.grid_key(x, y, s),
            #'/{}/tilt'.format(self.prefix): lambda addr, path, n, x, y, z: self.tilt(n, x, y, z),
        })

        #self.addMsgHandler('default', self.waffle_handler)
        #self.addMsgHandler('/sys/port', self.sys_port)
        #self.addMsgHandler('/sys/host', self.sys_host)
        #self.addMsgHandler('/sys/prefix', self.sys_prefix)

        #self.addMsgHandler('/sys/connect', self.sys_misc)
        #self.addMsgHandler('/sys/disconnect', self.sys_misc)
        #self.addMsgHandler('/sys/rotation', self.sys_misc)

        #self.addMsgHandler('/sys/info', self.sys_info)

        #self.app_callback = None

    #def sys_misc(self, addr, tags, data, client_address):
    #    pass

    def echo(self, addr, path, *args):
        print("incoming message from {}: {} {}".format(addr, path, args))
        # echo the message
        #self.send(path, *args, addr=addr)

    def sys_info(self, addr, path, *args):
        if path == '/sys/id':
            self.id = args[0]
        elif path == '/sys/size':
            self.width, self.height = (args[0], args[1])
        elif path == '/sys/rotation':
            self.rotation = args[0]


class VirtualGrid(aiosc.OSCProtocol):
    def __init__(self,id, xsize, ysize, port=0):
        #self.prefix = 'runcible'
        self.id = id
        self.width = xsize
        self.height = ysize
        self.rotation = None
        self.varibright = False
        #self.app_host = DEFAULT_APP_HOST
        #self.app_port = DEFAULT_APP_PORT
        self.prefix = id
        super().__init__(handlers={
            '/sys/exit': self.exit,
            '/sys/disconnect': lambda *args: self.disconnect,
            '/sys/{id,size,host,port,prefix,rotation}': self.sys_info,
            '/*/grid/key': self.grid_key,
            '/{}/tilt'.format(self.prefix): lambda addr, path, n, x, y, z: self.tilt(n, x, y, z),
            '//*': self.echo,
        })
        print("Virtual Grid: ", self.id, "X: ", self.width, "Y: ", self.height)

    def exit(self, *args):
        asyncio.get_event_loop().stop()

    def echo(self, addr, path, *args):
        print("incoming message from {}: {} {}".format(addr, path, args))
        # echo the message
        #self.send(path, *args, addr=addr)

    #def connection_made(self, transport):
    #    super().connection_made(transport)
    #    self.host, self.port = transport.get_extra_info('sockname')
    #    self.connect()

    def connect(self):
        pass
        #self.send('/sys/host', self.host)
        #self.send('/sys/port', self.port)
        #self.send('/sys/prefix', self.prefix)
        #self.send('/sys/info', self.host, self.port)

    def disconnect(self):
        self.transport.close()

    def sys_info(self, addr, path, *args):
        if path == '/sys/id':
            self.id = args[0]
        elif path == '/sys/size':
            self.width, self.height = (args[0], args[1])
        elif path == '/sys/rotation':
            self.rotation = args[0]

        # TODO: refine conditions for reinitializing
        # in case rotation, etc. changes
        # Note: arc will report 0, 0 for its size
        if all(x is not None for x in [self.id, self.width, self.height, self.rotation]):
            if re.match('^m\d+$', self.id):
                self.varibright = True
            self.ready()

    def ready(self):
        print ("using grid on port :%s" % self.id)

    #maybe this code moves into a utility function so that child classes can over-ride grid_key and easily covert
    #also conversion messages should be taken from config not hard caded
    def grid_key(self, addr, path, *args):
        #translate grid_key from device grid coords to spanned grid coords
        #print(args)
        x, y, s = args
        print("raw grid_key: ",path,x,y,s)
        if path == '/m40h-001/grid/key':
            x=abs(x-7)
            print("spanned grid_key: ",x,y,s)
        elif path == '/m40h-002/grid/key':
            r = x
            x = y+8
            y = r
            print("spanned grid_key: ",x,y,s)

        self.led_set(x,y,s)

    def tilt(self, n, x, y, z):
        pass

    def led_set(self, x, y, s):
        #translate grid_key from spanned grid coords to device grid coords
        #TODO: use the destination ports defined in the config file instead of hardcoding
        if x < 8: 
            x = abs(7-x)
            print("sending /mh40h-001/grid/led/set", x,y,s)
            path = '/m40h-001/grid/led/set'
            asyncio.async(aiosc.send(('127.0.0.1', 8000), path, x, y, s))
        else:
            r = y
            y = abs(x-8)
            x = r
            print("sending /m40h-002/grid/key ", x,y,s)
            path = '/m40h-002/grid/led/set'
            asyncio.async(aiosc.send(('127.0.0.1', 8001), path, x, y, s))

    def led_all(self, s):
        pass
        #self.send('/{}/grid/led/all'.format(self.prefix), s)

    def led_map(self, x_offset, y_offset, data):
        args = [pack_row(data[i]) for i in range(8)]
        #self.send('/{}/grid/led/map'.format(self.prefix), x_offset, y_offset, *args)

    def led_row(self, x_offset, y, data):
        args = [pack_row(data[i*8:(i+1)*8]) for i in range(len(data) // 8)]
        #self.send('/{}/grid/led/row'.format(self.prefix), x_offset, y, *args)

    def led_col(self, x, y_offset, data):
        args = [pack_row(data[i*8:(i+1)*8]) for i in range(len(data) // 8)]
        #self.send('/{}/grid/led/col'.format(self.prefix), x, y_offset, *args)

    def led_intensity(self, i):
        pass
        #self.send('/{}/grid/led/intensity'.format(self.prefix), i)

    def led_level_set(self, x, y, l):
        if self.varibright:
            pass
        #    self.send('/{}/grid/led/level/set'.format(self.prefix), x, y, l)
        else:
            pass
        #    self.led_set(x, y, l >> 3 & 1)

    def led_level_all(self, l):
        if self.varibright:
            pass
            #self.send('/{}/grid/led/level/all'.format(self.prefix), l)
        else:
            pass
            #self.led_all(l >> 3 & 1)

    def led_level_map(self, x_offset, y_offset, data):
        if self.varibright:
            args = itertools.chain(*data)
            #self.send('/{}/grid/led/level/map'.format(self.prefix), x_offset, y_offset, *args)
        else:
            pass
            #self.led_map(x_offset, y_offset, [[l >> 3 & 1 for l in row] for row in data])

    def led_level_row(self, x_offset, y, data):
        if self.varibright:
            pass
            #self.send('/{}/grid/led/level/row'.format(self.prefix), x_offset, y, *data)
        else:
            pass
            #self.led_row(x_offset, y, [l >> 3 & 1 for l in data])

    def led_level_col(self, x, y_offset, data):
        if self.varibright:
            pass
            #self.send('/{}/grid/led/level/col'.format(self.prefix), x, y_offset, *data)
        else:
            pass
            #self.led_col(x, y_offset, [l >> 3 & 1 for l in data])

    def tilt_set(self, n, s):
        pass
        #self.send('/{}/tilt/set'.format(self.prefix), n, s)

# very similar to SerialOSC except that:
# it reads a config file as part of the initialisation process
# and then creates a virtual device based on the config file
# If real devices are detected, they get created as normal
# which means that the calling program must specify the "route" app for each real device as well as the actual app for the virtual device
# (aim is to fix this later so that real devices which are specified as part of the spanned virtual device get the route app by default)
# TODO: work out how to establish a connection between the virtual device and the route app running on each real device
# probably through the definition of grid/key processor for the virtual device??? 
class SpannedSerialOsc(monome.BaseSerialOsc):
    def __init__(self, app_factories, config='runcible-128.conf', loop=None):
        super().__init__()
        self.app_factories = app_factories
        self.app_instances = {}
        self.devices    = {}
        #self.services   = {}
        self.offsets    = {}
        self.transtbl   = {}
        #self.watcher = MonomeWatcher(self)

        self.parse_config(config)

        if loop is None:
            loop = asyncio.get_event_loop()
        self.loop = loop

    def parse_config(self, filename):
        #from ConfigParser import RawConfigParser
        from configparser import RawConfigParser
        import io
        config = RawConfigParser()
        config.readfp(io.open(filename, 'r', encoding='utf_8_sig'))
        for s in config.sections():
            port = int(config.get(s, 'port'))
            config.remove_option(s, 'port')

            xsize, ysize = [int(d) for d in config.get(s, 'size').split(",")]
            config.remove_option(s, 'size')

            x_off, y_off = [int(d) for d in config.get(s, 'offset').split(",")]
            config.remove_option(s, 'offset')
            self.offsets[s] = (x_off, y_off)

            for device, offset in config.items(s):
                x_off, y_off = [int(d) for d in offset.split(",")]
                if device in self.offsets:
                    if (x_off, y_off) != self.offsets[device]:
                        raise RuntimeError("conflicting offsets for device %s" % device)
                self.offsets[device] = (x_off, y_off)

                if s in self.transtbl: self.transtbl[s].append(device)
                else: self.transtbl[s] = [device]
                if device in self.transtbl: self.transtbl[device].append(s)
                else: self.transtbl[device] = [s]
            self.add_virtual(s, xsize, ysize, port)
            #self.device_added(s, xsize, ysize, port)

    def add_virtual(self, name, xsize, ysize, port=0):
        #device = VirtualGrid(name, xsize, ysize, port)
        #self.devices[name] = device
        asyncio.async(self.autoconnect(name, self.app_factories[name], port)) # this may not be the right app
        print("add_virtual:",name,self.app_factories[name],port)
        print("actual devices: ", self.transtbl[name])


    def device_added(self, id, type, port):
        super().device_added(id, type, port)

        if id in self.app_factories:
            asyncio.async(self.autoconnect(id, self.app_factories[id], port))
            print("device added: ", id, self.app_factories[id], port)
        elif '*' in self.app_factories:
            asyncio.async(self.autoconnect(id, self.app_factories['*'], port))
            print("device added: ", id, '*', port)

    @asyncio.coroutine
    def autoconnect(self, id, app, port):
        transport, app = yield from self.loop.create_datagram_endpoint(
            app,
            local_addr=('127.0.0.1', port),
            remote_addr=('127.0.0.1', 0)
        )

        apps = self.app_instances.get(id, [])
        apps.append(app)
        self.app_instances[id] = apps

    def device_removed(self, id, type, port):
        super().device_removed(id, type, port)

        if id in self.app_instances:
            for app in self.app_instances[id]:
                app.disconnect()
            del self.app_instances[id]



@asyncio.coroutine
def create_spanned_serialosc_connection(app_or_apps, loop=None):
    if isinstance(app_or_apps, dict):
        apps = app_or_apps
    else:
        apps = {'*': app_or_apps}

    if loop is None:
        loop = asyncio.get_event_loop()

#TODO set the remote address based on the config file
    transport, serialosc = yield from loop.create_datagram_endpoint(
        lambda: SpannedSerialOsc(apps),
        local_addr=('127.0.0.1', 0),
        remote_addr=('127.0.0.1', 9000)
    )

    return serialosc
