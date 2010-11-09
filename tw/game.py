import time
import datetime
from tornado import ioloop

import server
import market
import parser
import world
import warden

LAUNCHING, WAITING, PREGAME, BUILDING, PLAYING, POSTGAME = range(6)

AUTH_TABLE = {
    'sixthgear': 'sixthgear',
    'mjard': 'mjard',
}

class Game(object):
    """
    Main Game controller object.
    """
    
    def __init__(self):
        self.state = LAUNCHING
        self.next_game_time = datetime.datetime.now() \
            + datetime.timedelta(seconds=5)
        self.pregame_delay = 5
        self.tick = 0
        self.players = {}
        self.world = world.World()
        self.server = None
        self.timer = None
        self.warden = warden.Warden()
                   
    def run(self, port=4000):
        """
        Let's start this machine
        """
        self.state = LAUNCHING
        self.server = server.Server(port)
        # hacky-hack event listeners
        self.server.on_new_connection = self.on_connect
        self.server.on_dropped_connection = self.on_disconnect
        self.server.on_start = self.on_start
        self.server.on_stop = self.on_stop
        self.server.on_read = self.on_read
        self.server.start()
        ioloop.IOLoop.instance().start()

    def on_start(self): 
        """
        After the server is up, find out if we should wait to start the game,
        or get going ASAP.
        """
        print 'TW is ready to rock on port %d.' % self.server.port
        if datetime.datetime.now() > self.next_game_time:
            self.open_pregame()
        else:
            print 'WAITING: NEXT GAME at %s.' % self.next_game_time
            self.timer = ioloop.PeriodicCallback(self.waiting_update, 1000)
            self.timer.start()        
            self.state = WAITING        

    def waiting_update(self):
        """
        This periodic function is called when the server is in WAITING state
        and is used solely to determine if it is time to start allowing
        connections for the next game.
        """
        if self.state == WAITING:
            if datetime.datetime.now() > self.next_game_time:
                self.open_pregame()
            
    def open_pregame(self):
        """
        So gametime is here, let's allow connections, in preparation for the 
        game. This is to allow every bot that wants to play a chance to get here 
        before the ticks start rolling.
        """
        assert self.state in (LAUNCHING, WAITING, POSTGAME)
        self.state = PREGAME
        print 'PREGAME: Allowing connections, game begins in %d seconds' \
            % self.pregame_delay
        self.timer = None
        ioloop.IOLoop.instance().add_timeout(time.time() \
            + self.pregame_delay, self.start_game)
        
    def start_game(self):
        """
        Begin the actual game.
        """    
        assert self.state in (PREGAME,)
        print 'BUILDING: creating game world and market'
        self.state = BUILDING
        # generate planets
        # generate market
        # create players
        self.state = PLAYING
        print 'PLAYING: starting turns'
        self.timer = ioloop.PeriodicCallback(self.update, 1500)
        self.timer.start()        
    
    def shutdown(self):
        """
        Goodnight! This is called from the SIGINT handler in the launch script.
        """
        print 'Shutting down...'
        if self.timer: 
            self.timer.stop()
        self.server.stop()
        ioloop.IOLoop.instance().stop()        
                
    def on_stop(self): 
        print 'Server stopped.'
        
    def on_connect(self, connection):
        """
        Called whenever the server has a new connection.
        """        
        print 'new connection from %s.' % connection.address[0]
        # report this connection to warden
        self.warden.report_connection()
        if self.state == WAITING:
            connection.send('NEXT GAME AT %s\n' % self.next_game_time)
            connection.disconnect()            
        if self.state in (PREGAME, BUILDING, PLAYING):            
            connection.state = server.AUTH
            connection.send('AUTH\n')
    
    def authenticate(self, connection, token):
        """
        """
        if AUTH_TABLE.has_key(token):
            username = AUTH_TABLE[token]
            plist = filter(lambda x: x[1].name == username, \
                self.players.items())
            if not plist:
                player = world.Player(connection)
                player.name = username
                self.players[connection.fileno] = player
                print '%s has joined the game.' % player.name
            else:
                fileno, player = plist[0]
                self.players[fileno].disconnect()
                del self.players[fileno]
                
                self.players[connection.fileno] = player
                self.players[connection.fileno].connection = connection
                
                print '%s has rejoined the game.' % player.name
            
            connection.state = server.AUTHENTICATED            
            connection.send('WELCOME %s\n' % player.name)            
        else:
            print '%s: INVALID TOKEN: %s' % (connection.fileno, token)
            connection.send('INVALID TOKEN\n')
            connection.disconnect()
            
    def on_disconnect(self, connection):
        if self.players.has_key(connection.fileno):
            self.players[connection.fileno].disconnect()
            print '%s has disconnected.' \
                % self.players[connection.fileno].name
            # del self.players[connection.fileno]
            
        
    def on_read(self, connection, data): 
        """
        Client sent us something. Let's stick it in the command queue to 
        examine later.
        """        
        command = data.strip()
        if connection.state == server.AUTH:
            self.authenticate(connection, command)
        elif connection.state == server.AUTHENTICATED:
            player = self.players[connection.fileno]
            player.command_queue.append(command)
                                    
    def update(self):
        """
        Called every 1500ms.
        """
        self.tick += 1
        
        # 1. read connections
        # 2. parse commands
        
        for fileno, p in self.players.items():            
            if len(p.command_queue) > 1:
                print 'Error for %s: more than one command for this turn.' % p
                p.output('Error: more than one command for this turn. \n')
                p.command_queue = []
                continue                
            elif p.command_queue:                
                command = p.command_queue.pop(0)
                print parser.parse(command, self.world, p)
        
        # 3. update game state
        # DETECT DEADLOCKS!
        
        # 4. simulate market
        
        # 5. write to connections
        # write common output
        
        print 'sending tick %d...' % self.tick
        self.server.sendall('TURN %d\n' % self.tick)
        
        # write individual output
        for p in self.players.values():
            p.flush()
        
        # send ready command
        self.server.sendall('#\n')
