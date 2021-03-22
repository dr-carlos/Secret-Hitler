import random
from enum import Enum
from PIL import Image
from secret_hitler import config


class Player:
    def __init__(self, player_id):
        self.player_id = player_id
        self.role = None
        self.dead = False

    def get_id(self):
        return self.player_id

    def get_party(self):
        if self.role == 'Hitler' or self.role == 'Fascist':
            return 'Fascist'
        else:
            return 'Liberal'

class Game:

    def __init__(self, channel_id, game_id, max_players, admin_id):
        self.president_id = 0
        self.president = None
        self.chancellor = None
        self.nominated = None
        self.prev_president = None
        self.prev_chancellor = None
        self.prev_chancellor_id = -1
        self.prev_president_id = -1
        self.liberal_board = 0
        self.fascist_board = 0
        self.failed_votes = 0
        self.channel_id = channel_id
        self.admin_id = admin_id
        self.max_players = max_players
        self.game_id = game_id
        self.deck = ['L', 'L', 'L', 'L', 'L', 'L', 'F', 'F', 'F', 'F', 'F', 'F', 'F', 'F', 'F', 'F', 'F']
        self.discard = []
        self.nominated = None
        self.policies = []
        self.investigated_one = False
        self.investigated = False
        self.peeked = False
        self.executed_one = False
        self.executed_two = False
        random.shuffle(self.deck)
        self.players = []
        self.dead = []
        self.state = GameStates.GAME_STARTING
        self.add_player(admin_id)
        self.votes = {}

    def add_player(self, player_id):
        if len(self.players) == self.max_players:
            return False
        self.players.append(Player(player_id))
        return True

    def start_game(self):
        if len(self.players) < self.max_players:
            return False

        # Shuffle seets
        random.shuffle(self.players)

        # Shuffle roles
        roles = config.configuration[self.max_players]["roles"]
        random.shuffle(roles)

        for i in range(self.max_players):
            self.players[i].role = roles[i]

        self.president = self.players[0]
        return True

    def nominate(self, player_id):
        player = self.get_player(player_id)
        player_num = len(self.players)
        if player_num <= 5:
            print(self.prev_chancellor_id)
            print(player_id)
            if self.chancellor is not None and self.chancellor.player_id is player_id:
                return False
        elif player_num > 5:
            if (self.chancellor is not None and self.chancellor.player_id is player_id) or self.prev_president_id is player_id:
                return False

        if self.president is not None and self.president.player_id is player_id:
            return False
        self.nominated = player
        self.state = GameStates.ELECTION
        return True

    def vote(self, player_id, vote):
        for id, s_v in self.votes.items():
            if id == player_id:
                return False

        if len(self.votes) == len(self.players):
            return False

        self.votes[player_id] = vote
        return True

    def calculate_votes(self):
        yes = 0
        no = 0
        for id, vote in self.votes.items():
            if vote == 'y':
                yes = yes+1
            elif vote == 'n':
                no = no+1

        self.votes = {}

        if yes > no:
            if self.chancellor is None and self.prev_chancellor_id == -1:
                self.prev_chancellor_id = -1
            else:
                self.prev_chancellor = self.chancellor
                self.prev_chancellor_id = self.chancellor.player_id
            self.chancellor = self.nominated
            if self.chancellor.role == "Hitler" and self.fascist_board >= 3:
                self.state = GameStates.GAME_OVER
                self.winner = "Fascist"
                return False
            self.failed_votes = 0
            self.state = GameStates.LEGISLATIVE_PRESIDENT
            return True
        else:
            self.nominated = None
            self.failed_votes = self.failed_votes + 1
            if self.failed_votes > 3:
                policy = self.get_policy()
                self.place_policy(policy)
                if self.state == GameStates.GAME_OVER:
                    self.policies.clear()
                    return False
                self.policies.clear()
                if policy == 'L':
                    self.state = GameStates.NOMINATION
                    return False
                else:
                    if self.fascist_board == 1 and not self.investigated_one and self.max_players > 8:
                        self.state = GameStates.INVESTIGATION
                        return False
                    if self.fascist_board == 2 and not self.investigated and self.max_players > 6:
                        print(self.max_players)
                        print("HH")
                        self.state = GameStates.INVESTIGATION
                        return False
                    elif self.fascist_board == 3 and not self.peeked:
                        if self.max_players > 6:
                            self.state = GameStates.SPECIAL_ELECTION
                        else:
                            self.state = GameStates.POLICY_PEEK
                        return False
                    elif self.fascist_board == 4 and not self.executed_one:
                        self.state = GameStates.EXECUTION
                        return False
                    elif self.fascist_board == 5 and not self.executed_two:
                        self.state = GameStates.EXECUTION
                        return False

                    self.state = GameStates.NOMINATION
                    return False
                # Do some stuff here
                return False
            self.set_president()
            return False

    def start_nomination(self):
        self.state = GameStates.NOMINATION

    def get_players(self):
        return self.players

    def get_id(self):
        return self.game_id

    def has_player(self, player_id):
        for player in self.players:
            if player_id == player.get_id():
                return True
        return False

    def get_player(self, player_id):
        for player in self.players:
            if player_id == player.get_id():
                return player
        return None

    def return_path_to_fascist_board(self):
        if self.fascist_board == 0:
            if self.max_players < 7:
                return 'secret_hitler/img/FascistBoard1.png'
            elif self.max_players < 9:
                return 'secret_hitler/img/FascistBoard2.png'
            return 'secret_hitler/img/FascistBoard3.png'
        return "secret_hitler/img/fascist_" + str(self.game_id) + ".png"

    def return_path_to_liberal_board(self):
        if self.liberal_board == 0:
            return 'secret_hitler/img/LiberalBoard.png'
        return "secret_hitler/img/liberal_" + str(self.game_id) + ".png"

    def set_president(self):
        if self.president_id >= (len(self.players) - 1):
            self.president_id = 0
        else:
            self.president_id = self.president_id+1
        self.prev_president_id = self.president.player_id
        self.prev_president = self.president
        self.president = self.players[self.president_id]

    def get_policy(self):
        if len(self.deck) == 0:
            self.deck = self.discard.copy()
            self.discard.clear()
            random.shuffle(self.deck)
        return self.deck.pop(0)

    def place_policy(self, policy):
        if 'L' in policy:
            self.liberal_board = self.liberal_board+1
        if 'F' in policy:
            self.fascist_board = self.fascist_board+1

        if self.liberal_board >= 5:
            self.state = GameStates.GAME_OVER
            self.winner = "Liberal"
        elif self.fascist_board >= 6:
            self.state = GameStates.GAME_OVER
            self.winner = "Fascist"

    def president_legislative(self):
        policy1 = self.get_policy()
        policy2 = self.get_policy()
        policy3 = self.get_policy()
        self.policies.append(policy1)
        self.policies.append(policy2)
        self.policies.append(policy3)

        img1 = Image.open('secret_hitler/img/policy_liberal.png')
        img1 = img1.resize((292, 450))
        img2 = Image.open('secret_hitler/img/policy_fascist.png')
        img2 = img2.resize((292, 450))

        new_size = 3*292 + 20

        img_new = Image.new('RGBA', (new_size, 470), (255, 0, 0, 0))
        if policy1 == 'L':
            img_new.paste(img1, (10, 10))
        else:
            img_new.paste(img2, (10, 10))

        if policy2 == 'L':
            img_new.paste(img1, (292+10,10))
        else:
            img_new.paste(img2, (292+10,10))

        if policy3 == 'L':
            img_new.paste(img1, (2*292+10,10))
        else:
            img_new.paste(img2, (2*292+10,10))
        img_new.save("secret_hitler/img/president_"+str(self.game_id)+".png")

    def policy_peek(self):
        policy1 = self.get_policy()
        policy2 = self.get_policy()
        policy3 = self.get_policy()

        img1 = Image.open('secret_hitler/img/policy_liberal.png')
        img1 = img1.resize((292, 450))
        img2 = Image.open('secret_hitler/img/policy_fascist.png')
        img2 = img2.resize((292, 450))

        new_size = 3 * 292 + 20

        img_new = Image.new('RGBA', (new_size, 470), (255, 0, 0, 0))
        if policy1 == 'L':
            img_new.paste(img1, (10, 10))
        else:
            img_new.paste(img2, (10, 10))

        if policy2 == 'L':
            img_new.paste(img1, (292 + 10, 10))
        else:
            img_new.paste(img2, (292 + 10, 10))

        if policy3 == 'L':
            img_new.paste(img1, (2 * 292 + 10, 10))
        else:
            img_new.paste(img2, (2 * 292 + 10, 10))
        img_new.save("secret_hitler/img/policypeek_" + str(self.game_id) + ".png")

        self.deck.insert(0, policy3)
        self.deck.insert(0, policy2)
        self.deck.insert(0, policy1)

        self.peeked = True

    def printBoard(self):
        img1 = Image.open('secret_hitler/img/liberal_policy.png')

        img_new = Image.open('secret_hitler/img/LiberalBoard.png')
        for i in range(self.liberal_board):
            img_new.paste(img1, config.configuration["liberal_board"][i])
        img_new.save("secret_hitler/img/liberal_" + str(self.game_id) + ".png")

        img2 = Image.open('secret_hitler/img/fascist_policy.png')

        if self.max_players < 7:
            img_new_2 = Image.open('secret_hitler/img/FascistBoard1.png')
        elif self.max_players < 9:
            img_new_2 = Image.open('secret_hitler/img/FascistBoard2.png')
        else:
            img_new_2 = Image.open('secret_hitler/img/FascistBoard3.png')

        for i in range(self.fascist_board):
            img_new_2.paste(img2, config.configuration["fascist_board"][i])
        img_new_2.save("secret_hitler/img/fascist_" + str(self.game_id) + ".png")

    def chancellor_legislative(self):
        policy1 = self.policies[0]
        policy2 = self.policies[1]

        img1 = Image.open('secret_hitler/img/policy_liberal.png')
        img1 = img1.resize((292, 450))
        img2 = Image.open('secret_hitler/img/policy_fascist.png')
        img2 = img2.resize((292, 450))

        new_size = 2*292 + 20

        img_new = Image.new('RGBA', (new_size, 470), (255, 0, 0, 0))
        if policy1 == 'L':
            img_new.paste(img1, (10, 10))
        else:
            img_new.paste(img2, (10, 10))

        if policy2 == 'L':
            img_new.paste(img1, (292+10,10))
        else:
            img_new.paste(img2, (292+10,10))

        img_new.save("secret_hitler/img/chancellor_"+str(self.game_id)+".png")

    def discard_policy(self, player_id, card):
        card = card.upper()
        if (self.state is GameStates.LEGISLATIVE_PRESIDENT and self.president.player_id is player_id) or (self.state is GameStates.LEGISLATIVE_CHANCELLOR and self.chancellor.player_id is player_id):
            if card == 'F' or card == 'L':
                for i in range(len(self.policies)):
                    if self.policies[i] == card:
                        popped =  self.policies[i]
                        self.policies.pop(i)
                        self.discard.append(popped)
                        if len(self.policies) == 1:
                            policy = self.policies[0]
                            self.place_policy(self.policies[0])
                            if self.state == GameStates.GAME_OVER:
                                return True
                            self.policies.clear()
                            if policy == 'L':
                                self.state = GameStates.NOMINATION
                                return True
                            else:
                                if self.fascist_board == 1 and not self.investigated_one and self.max_players > 8:
                                    self.state = GameStates.INVESTIGATION
                                    return True
                                elif self.fascist_board == 2 and not self.investigated and self.max_players > 6:
                                    print(self.max_players)
                                    print("HH")
                                    self.state = GameStates.INVESTIGATION
                                    return True
                                elif self.fascist_board == 3 and not self.peeked:
                                    if self.max_players > 6:
                                        self.state = GameStates.SPECIAL_ELECTION
                                    else:
                                        self.state = GameStates.POLICY_PEEK
                                    return True
                                elif self.fascist_board == 4 and not self.executed_one:
                                    self.state = GameStates.EXECUTION
                                    return True
                                elif self.fascist_board == 5 and not self.executed_two:
                                    self.state = GameStates.EXECUTION
                                    return True

                                self.state = GameStates.NOMINATION
                                return True
                            # Do some stuff here
                            return True
                        elif len(self.policies) == 2:
                            self.state = GameStates.LEGISLATIVE_CHANCELLOR
                            return True
                return False
            return False
        return False

    def execute_player(self, player_id):
        for i in range(len(self.players)):
            player = self.players[i]
            if player.player_id == player_id:
                self.players.pop(i)
                self.dead.append(player)
                if self.fascist_board == 4:
                    self.executed_one = True
                elif self.fascist_board == 5:
                    self.executed_one = True
                return player
        return None

    def restart_game(self):
        for player in self.dead:
            self.players.append(player)
        self.dead.clear()
        self.discard.clear()
        self.president_id = 0
        self.president = None
        self.chancellor = None
        self.nominated = None
        self.prev_president = None
        self.prev_chancellor = None
        self.liberal_board = 0
        self.fascist_board = 0
        self.failed_votes = 0
        self.deck = ['L', 'L', 'L', 'L', 'L', 'L', 'F', 'F', 'F', 'F', 'F', 'F', 'F', 'F', 'F', 'F', 'F']
        self.nominated = None
        self.policies.clear()
        self.investigated = False
        self.peeked = False
        self.executed_one = False
        self.executed_two = False
        random.shuffle(self.deck)
        self.votes = {}
        self.state = GameStates.GAME_STARTING


class GameStates(Enum):
    GAME_STARTING = 1
    NOMINATION = 2
    ELECTION = 3
    LEGISLATIVE_PRESIDENT = 4
    LEGISLATIVE_CHANCELLOR = 5
    VETO = 6
    INVESTIGATION = 7
    SPECIAL_ELECTION = 8
    POLICY_PEEK = 9
    EXECUTION = 10
    GAME_OVER = 11
