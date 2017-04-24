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

class SpannedMonome(aiosc.OSCProtocol):
    def __init__(self, prefix='/python'):
        self.prefix = prefix.strip('/')
        self.id = None
        self.width = None
        self.height = None
        self.rotation = None
        self.varibright = False
        #work out how to have a reference to the spanned grids

        super().__init__(handlers={
            '/sys/disconnect': lambda *args: self.disconnect,
            #'/sys/connect': lambda *args: self.connect,
            '/sys/{id,size,host,port,prefix,rotation}': self.sys_info,
            '/{}/grid/key'.format(self.prefix): lambda addr, path, x, y, s: self.grid_key(x, y, s),
            '/{}/tilt'.format(self.prefix): lambda addr, path, n, x, y, z: self.tilt(n, x, y, z),
            #'//*': self.echo,
        })

    def connection_made(self, transport):
        super().connection_made(transport)
        self.host, self.port = transport.get_extra_info('sockname')
        self.connect()

    def connect(self):
        self.send('/sys/host', self.host)
        self.send('/sys/port', self.port)
        self.send('/sys/prefix', self.prefix)
        self.send('/sys/info', self.host, self.port)

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
        pass

    def grid_key(self, x, y, s):
        pass
        #get grid_key from spanned grids

    def tilt(self, n, x, y, z):
        pass

    def led_set(self, x, y, s):
        self.send('/{}/grid/led/set'.format(self.prefix), x, y, s)
        #send messages to spanned grids

    def led_all(self, s):
        self.send('/{}/grid/led/all'.format(self.prefix), s)

    def led_map(self, x_offset, y_offset, data):
        args = [pack_row(data[i]) for i in range(8)]
        self.send('/{}/grid/led/map'.format(self.prefix), x_offset, y_offset, *args)

    def led_row(self, x_offset, y, data):
        args = [pack_row(data[i*8:(i+1)*8]) for i in range(len(data) // 8)]
        self.send('/{}/grid/led/row'.format(self.prefix), x_offset, y, *args)

    def led_col(self, x, y_offset, data):
        args = [pack_row(data[i*8:(i+1)*8]) for i in range(len(data) // 8)]
        self.send('/{}/grid/led/col'.format(self.prefix), x, y_offset, *args)

    def led_intensity(self, i):
        self.send('/{}/grid/led/intensity'.format(self.prefix), i)

    def led_level_set(self, x, y, l):
        if self.varibright:
            self.send('/{}/grid/led/level/set'.format(self.prefix), x, y, l)
        else:
            self.led_set(x, y, l >> 3 & 1)

    def led_level_all(self, l):
        if self.varibright:
            self.send('/{}/grid/led/level/all'.format(self.prefix), l)
        else:
            self.led_all(l >> 3 & 1)

    def led_level_map(self, x_offset, y_offset, data):
        if self.varibright:
            args = itertools.chain(*data)
            self.send('/{}/grid/led/level/map'.format(self.prefix), x_offset, y_offset, *args)
        else:
            self.led_map(x_offset, y_offset, [[l >> 3 & 1 for l in row] for row in data])

    def led_level_row(self, x_offset, y, data):
        if self.varibright:
            self.send('/{}/grid/led/level/row'.format(self.prefix), x_offset, y, *data)
        else:
            self.led_row(x_offset, y, [l >> 3 & 1 for l in data])

    def led_level_col(self, x, y_offset, data):
        if self.varibright:
            self.send('/{}/grid/led/level/col'.format(self.prefix), x, y_offset, *data)
        else:
            self.led_col(x, y_offset, [l >> 3 & 1 for l in data])

    def tilt_set(self, n, s):
        self.send('/{}/tilt/set'.format(self.prefix), n, s)


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

    #def sys_port(self, addr, tags, data, client_address):
    #    self.waffle_send('/sys/port', self.app_port)
    #    self.app_port = data[0]
    #    self.waffle_send('/sys/port', self.app_port)
    
    #def sys_host(self, addr, tags, data, client_address):
    #    self.waffle_send('/sys/host', self.app_host)
    #    self.app_host = data[0]
    #    self.waffle_send('/sys/host', self.app_host)
    
    #def sys_prefix(self, addr, tags, data, client_address):
    #    self.prefix = fix_prefix(data[0])
    #    self.waffle_send('/sys/prefix', self.prefix)
    
    #def sys_info(self, addr, tags, data, client_address):
    #    if len(data) == 2: host, port = data
    #    elif len(data) == 1: host, port = self.app_host, data[0]
    #    elif len(data) == 0: host, port = self.app_host, self.app_port
    #    else: return
    #    
    #    self.waffle_send_any(host, port, '/sys/id', self.id)
    #    self.waffle_send_any(host, port, '/sys/size', self.xsize, self.ysize)
    #    self.waffle_send_any(host, port, '/sys/host', self.app_host)
    #    self.waffle_send_any(host, port, '/sys/port', self.app_port)
    #    self.waffle_send_any(host, port, '/sys/prefix', self.prefix)
    #    self.waffle_send_any(host, port, '/sys/rotation', 0)
    
    # FIXME: we have to redefine these until the client behaviour is figured out 
    #def waffle_send_any(self, host, port, path, *args):
    #    msg = OSCMessage(path)
    #    map(msg.append, args)
    #    client = OSCClient()
    #    client.sendto(msg, (host, port), timeout=0)
    
    #def waffle_send(self, path, *args):
    #    msg = OSCMessage(path)
    #    map(msg.append, args)
    #    client = OSCClient()
    #    client.sendto(msg, (self.app_host, self.app_port), timeout=0)

# very similar to SerialOSC except that:
# it reads a config file as part of the initialisation process
# and then creates a virtual device based on the config file
# If real devices are detected, they get created as normal
# which means that the calling program must specify the "route" app for each real device as well as the actual app for the virtual device
# (aim is to fix this later so that real devices which are specified as part of the spanned virtual device get the route app by default)
# TODO: work out how to establish a connection between the virtual device and the route app running on each real device
# probably through the definition of grid/key processor for the virtual device??? 
class SpannedSerialOsc(monome.BaseSerialOsc):
    def __init__(self, app_factories, config='griddle-128.conf', loop=None):
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
    
    def add_virtual(self, name, xsize, ysize, port=0):
        device = Virtual(name, xsize, ysize, port)
        self.devices[name] = device
        asyncio.async(self.autoconnect(name, self.app_factories[name], port))
        print("add_virtual:",name,self.app_factories[name],port)
        print("actual devices: ", self.transtbl[name])

        #sphost, spport = device.server_address
        #service_name = '%s-%s' % (GRIDDLE_SERVICE_PREFIX, name)
        #self.services[name] = pybonjour.DNSServiceRegister(name=service_name,
        #    regtype=REGTYPE,
        #    port=port,
        #    callBack=None)
        #print "creating %s (%d)" % (name, spport)
        #device.app_callback = self.route  #what's the equivalent serialoscd approach here?

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

    #def monome_discovered(self, serviceName, host, port):
    #    name = serviceName.split()[-1].strip('()') # take serial
    #    if not name in self.offsets: # only take affected devices
    #        return
    #    
    #    # FIXME: IPV4 and IPv6 are separate services and are resolved twice
    #    if not self.devices.has_key(name):
    #        monome = Monome(name, (host, port))
    #        print "%s discovered" % name
    #        self.devices[name] = monome
    #        self.devices[name].app_callback = self.route
    
    #def monome_removed(self, serviceName):
    #    name = serviceName.split()[-1].strip('()') # take serial
    #    # FIXME: IPV4 and IPv6 are separate services and are removed twice
    #    if self.devices.has_key(name):
    #        self.devices[name].close()
    #        del self.devices[name]
    #        print "%s removed" % name
    #    return
    
    def route(self, source, addr, tags, data):
        tsign = 1 if len(self.transtbl[source]) > 1 else -1
        
        # we have to sort devices by offset for correct splitting of row messages
        # FIXME: need to move all the offset calculation / clipping / tsign stuff to the config parser
        valid_targets = sorted(set(self.transtbl[source]) & set(self.devices.keys()), key=lambda k: self.offsets[k])
        valid_targets.reverse()
        
        #for d in self.transtbl[source]:
        for d in valid_targets:
            dest = self.devices[d]
            
            sxoff, syoff = self.offsets[source]
            dxoff, dyoff = self.offsets[d]
            xoff, yoff = tsign * (sxoff + dxoff),  tsign * (syoff + dyoff)
            
            # clipping adjustments
            if tsign == -1:
                minx = sxoff
                miny = syoff
                maxx = sxoff + self.devices[source].xsize
                maxy = syoff + self.devices[source].ysize
            else:
                minx = 0
                miny = 0
                maxx = dest.xsize
                maxy = dest.ysize
            
            if addr.endswith("grid/key") or addr.endswith("grid/led/set") or addr.endswith("grid/led/map"):
                x, y, args = data[0], data[1], data[2:]
                x, y = x - xoff, y - yoff
                if minx <= x < maxx and miny <= y < maxy:
                    dest.waffle_send('%s%s' % (dest.prefix, addr), x, y, *args)
            elif addr.endswith("grid/led/row"):
                x, y, args = data[0], data[1], data[2:]
                x, y = x - xoff, y - yoff
                args, remainder = args[:(maxx - minx) / 8], args[(maxx - minx) / 8:]
                if minx <= x < maxx and miny <= y < maxy:
                    dest.waffle_send('%s%s' % (dest.prefix, addr), x, y, *args)
                if len(remainder) > 0:
                    # tags=None (ignored)
                    self.route(source, addr, None, [x+dest.xsize, y]+remainder)
            elif addr.endswith("grid/led/col"):
                x, y, args = data[0], data[1], data[2:]
                x, y = x - xoff, y - yoff
                args, remainder = args[:(maxy - miny) / 8], args[(maxy - miny) / 8:]
                if minx <= x < maxx and miny <= y < maxy:
                    dest.waffle_send('%s%s' % (dest.prefix, addr), x, y, *args)
                if len(remainder) > 0:
                    # tags=None (ignored)
                    self.route(source, addr, None, [x, y+dest.ysize]+remainder)
            # special-case for /led/map in splitter configuration
            elif addr.endswith("grid/led/all") and tsign == -1:
                for x in range(minx, maxx, 8):
                    for y in range(miny, maxy, 8):
                        # tags=None (ignored)
                        self.route(source, "/grid/led/map", None, [x,y]+[0,0,0,0,0,0,0,0])
            else:
                dest.waffle_send('%s%s' % (dest.prefix, addr), data)
    
    #def run(self):
    #    while True:
    #        rlist = itertools.chain(self.devices.values(),
    #            self.services.values(),
    #            [self.watcher.sdRef])
    #        ready = select.select(rlist, [], [])
    #        for r in ready[0]:
    #            if isinstance(r, OSCServer):
    #                r.handle_request()
    #            elif isinstance(r, pybonjour.DNSServiceRef):
    #                pybonjour.DNSServiceProcessResult(r)
    #            else:
    #                raise RuntimeError("unknown stuff in select: %s", r)
    
    #def close(self):
    #    rlist = itertools.chain(self.devices.values(),
    #        self.services.values(),
    #        [self.watcher.sdRef])
    #    for s in rlist:
    #        s.close()

# research factories
# add an alternative method to autoconnect?  and or device_added such that the app is connected to the spanned device?
# the new device_added checks to see if added device is in the config file and automatically adds the route app to that spanned device (as per griddle)
# then the create_serialosc_connection method needs a version which connects an app to the virtual spanned device, as per griddle. need to work out the equivalent of virtual device. 

class Gate(aiosc.OSCProtocol):
    def __init__(self, prefix, bridge):
        self.prefix = prefix.strip('/')
        self.bridge = bridge

        super().__init__(handlers={
            '/{}/grid/led/set'.format(self.prefix):
                lambda addr, path, x, y, s:
                    # TODO: int(), because renoise sends float
                    self.bridge.led_set(int(x), int(y), int(s)),
            '/{}/grid/led/all'.format(self.prefix):
                lambda addr, path, s:
                    self.bridge.led_all(s),
            '/{}/grid/led/map'.format(self.prefix):
                lambda addr, path, x_offset, y_offset, *s:
                    self.bridge.led_map(x_offset, y_offset, list(itertools.chain(*[monome.unpack_row(r) for r in s]))),
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
        })

    def grid_key(self, x, y, s):
        self.send('/{}/grid/key'.format(self.prefix), x, y, s, addr=(self.bridge.app_host, self.bridge.app_port))
        #aiosc.send(('127.0.0.1', 3333), '/hello', 'world')
        path = '/{}/grid/key'.format(self.prefix)
        args = str(x+1) + ' ' + str(y) + ' ' + str(s)
        print(self.bridge.id,path, args, self.bridge.app_port)

class Bridge(monome.Monome):
    def __init__(self, bridge_host='127.0.0.1', bridge_port=8080, app_host='127.0.0.1', app_port=8000, app_prefix='/monome', loop=None):
        super().__init__('/bridge')
        if loop is None:
            loop = asyncio.get_event_loop()
        self.loop = loop

        self.bridge_host = bridge_host
        self.bridge_port = bridge_port

        self.app_host = app_host
        self.app_port = app_port
        self.app_prefix = app_prefix

    def ready(self):
        asyncio.async(self.init_gate())

    @asyncio.coroutine
    def init_gate(self):
        # there is no remote_addr=(self.app_host, self.app_port)
        # because some endpoint implementations (oscP5) are pretty careless
        # about their source ports
        transport, protocol = yield from self.loop.create_datagram_endpoint(
            lambda: Gate(self.app_prefix, self),
            local_addr=(self.bridge_host, self.bridge_port),
        )
        self.gate = protocol

    def grid_key(self, x, y, s):
        self.gate.grid_key(x, y, s)
        self.led_set(x, y, s)
        #path = '/{}/grid/key'.format(self.prefix)
        #args = str(x) + ' ' + str(y) + ' ' + str(s)
        #aiosc.send(('127.0.0.1', 3333), path, args)
        #path = '/{}/grid/key'.format(self.prefix)
        #args = str(x+1) + ' ' + str(y) + ' ' + str(s)
        #print(self.id,path, args)

#if __name__ == '__main__':
#    loop = asyncio.get_event_loop()
#    coro = monome.create_serialosc_connection({
#        '*': lambda: Bridge(bridge_port=8080, app_port=8000, app_prefix='/rove'),
#    }, loop=loop)
#    loop.run_until_complete(coro)
#    loop.run_forever()

class Hello(monome.Monome):
    def __init__(self):
        super().__init__('/hello')

    def grid_key(self, x, y, s):
        self.led_set(x, y, s)
        #send the grid_key message to the virtual monome
        path = '/{}/grid/key'.format(self.prefix)
        args = str(x+1) + ' ' + str(y) + ' ' + str(s)
        aiosc.send(('127.0.0.1', 3333), path, args)
        #self.send(path, args, addr=('127.0.0.1', 12510))
        print(self.id,path, args)

@asyncio.coroutine  #create a version which uses a spanned interface instead?
def create_spanned_serialosc_connection(app_or_apps, loop=None):
    if isinstance(app_or_apps, dict):
        apps = app_or_apps
    else:
        apps = {'*': app_or_apps}
   
    # set up the routing app for translating OSC messages between actual and virtual 
    #r1 = lambda: Bridge(bridge_port=8080, app_port=3333,app_prefix='/hello')
    #r2 = lambda: Bridge(bridge_port=8081, app_port=3333,app_prefix='/hello')
    r1 = lambda: Hello()
    r2 = lambda: Hello()

    #add the actual devices (hard coded for now)
    #apps.update({'m40h-001': r1, 'm40h-002': r2,})

    #device_loop = asyncio.get_event_loop()
    #transport, serialosc = yield from device_loop.create_datagram_endpoint(
    #    lambda: SerialOsc(apps),
    #    local_addr=('127.0.0.1', 0),
    #    remote_addr=('127.0.0.1', 12002)
    #)

    if loop is None:
        loop = asyncio.get_event_loop()

    #g1_transport, g1_serialosc = yield from loop.create_datagram_endpoint(
    #    lambda: SpannedSerialOsc(apps),
    #    local_addr=('127.0.0.1', 8080),
    #    remote_addr=('127.0.0.1', 3333)
    #)

    #g2_transport, g2_serialosc = yield from loop.create_datagram_endpoint(
    #    lambda: SpannedSerialOsc(apps),
    #    local_addr=('127.0.0.1', 8081),
    #    remote_addr=('127.0.0.1', 3333)
    #)

    device_apps = {'m40h-001': r1, 'm40h-002': r2,}
    transport, serialosc = yield from loop.create_datagram_endpoint(
        lambda: monome.SerialOsc(device_apps),
        local_addr=('127.0.0.1', 0),
        remote_addr=('127.0.0.1', 12002)
    )
    #return serialosc, g1_serialosc
    return serialosc
