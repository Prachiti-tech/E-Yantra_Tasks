#!/usr/bin/env python

# Importing the required libraries

from vitarana_drone.msg import edrone_cmd, location_custom
from sensor_msgs.msg import NavSatFix, LaserScan
from vitarana_drone.srv import Gripper, GripperRequest
from std_msgs.msg import Float32, String, Int32
from pid_tune.msg import PidTune
import rospy
import time
import tf
import math
import numpy as np
import csv
import os
import rospkg
from collections import OrderedDict
import sys

class Edrone():
    """
    This is the main class for Vitarana E-Drone.
    It handles
    ----------
        1) Initialization of variables
        2) PID tuning of Longitude, Latitude, and Altitude
        3) Callbacks for PID constants
        4) Basic Tasks like initalizing a node and Subscribing
        5) Obstacle handling
        6) Getting waypoints and travelling
    Note : [ Longitude, Latitude, Altitude ] is the convention followed
    Methods :
    ----------
        1) pid :
            The main PID algorithm (for Position control) runs when this method is called
        2) imu_callback :
            Its called when IMU messages are received
        3) gps_callback :
            Receive the setpoint as in coordinates in 3d space [Latitudes, Longitude, Altitude]
        4) altitude_set_pid :
            Callback to assign Kp,Ki,Kd for Altitude
        5) long_set_pid :
            Callback to assign Kp,Ki,Kd for Longitude
        6) lat_set_pid :
            Callback to assign Kp,Ki,Kd for Latitude
        7) range_bottom:
            Callback to get values of the bottom ranger sensor
        8) range_top:
            Callback to get values of the top ranger sensor
        9) gripper_callback:
            Callback for the finding if the drone is in range of gripper activation
        10) activate_gripper:
            Function Controlling gripper activation
        11) lat_to_x:
            Function for converting latitude to meters
        12) long_to_y:
            Function for converting longitude to meters
        13) controller :
            Function for checking if the drone has reached the checkpoint
            and setting a new checkpoint
        14) handle_obstacle_x_y :
            Function handles obstacle detection and avoidance
        15) provide_current_loc_as_target:
            Function for defining the safe distance from an obstacle
        16) landing_control:
            Function for handling the landing, scanning and gripper operations of the drone
        17) takeoff_control:
            Function handles take off operation of the drone
        18) target_refresh:
            Function refreshes the waypoint list to provide for new desitnation scanned by the Qr scanner
        19) target_list:
            Function generates new waypoints between the current location and destination and inserts into the waypoint list
        20) delete_inserted:
            Deleting the previously added waypoints in the list before refreshing the list for new waypoints
        
        21) get_gps_coordinates:
            Function creates the target and building list by decoding the data from the given csv file
    """

    def __init__(self):

        # Initializing ros node with name position_control
        rospy.init_node('position_controller',log_level=rospy.DEBUG)

        # Creating an instance of NavSatFix message and edrone_cmd message
        self.location = NavSatFix()
        self.drone_cmd = edrone_cmd()

        # Created a flag for changing the setpoints
        self.targets_achieved = 0

        # Counter for csv file
        self.csv_counter = 0

        # Counter Check if obstacle was deteceted
        self.obstacle_count = 0

        # Gripper check vaiable
        self.gripper_data = False

        # A multiplication factor to increase number of waypoints proportional to distance between final and initial
        self.stride = 0.01

        # Hardcoded initial target point
        """
        Building 1: lat: 18.9990965928, long: 72.0000664814, alt: 10.75
        Building 2: lat: 18.9990965925, long: 71.9999050292, alt: 22.2
        Building 3: lat: 18.9993675932, long: 72.0000569892, alt: 10.7
        """
        #0:takeoff,1:transverse,2:landing,3:takeoff W/P,4:transverse W/P,5:landing W/P
        self.states = 0
        
        #List of target buildings
        self.buiding_locations = []

        # Initial Longitude , latitude and altitude
        self.targets = [
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
        ]
    
        # Variable to store scanned waypoints
        self.scanned_target = [0.0, 0.0, 0.0]

        # Marker ids
        self.marker_id = 0

        # To store bottom range finder values
        self.range_finder_bottom = 0

        # Variable for top range finder sensor data
        # [1] right, [2] back, [3] left, [0,4] front w.r.t eyantra logo
        self.range_finder_top_list = [0.0, 0.0, 0.0, 0.0, 0.0]

        # Weights for left right sensor values
        self.weights_lr = [1.3, -1.3]

        # Counter for number of landings made
        self.bottom_count = 0

        # Offset altitude
        self.offset_alt = 3.00

        # Safety distances
        self.safe_dist_lat = 21.555/105292.0089353767
        self.safe_dist_long = 6/110692.0702932625

        # To store the x and y co-ordinates in meters
        self.err_x_m = 0.0
        self.err_y_m = 0.0

        # Number of waypoints initialized to -1
        self.n = -1

        # List to store waypoints Points calculated
        self.points = []

        # Check if height attained
        self.start_to_check_for_obstacles = False

        # Kp, Ki and Kd found out experimentally using PID tune
        # self.Kp = [125000.0, 125000.0, 1082*0.06]
        # self.Ki = [0.008*10*1.05,        0.008*10*1.05,         0.0*0.008]
        # self.Kd = [8493425, 8493425,  4476*0.3]
        # self.Kp = [0.06*1000*156*2*3*1.025, 0.06*1000*156*2*3*1.025, 1082*0.06]
        # self.Ki = [0.008*10*1.05,        0.008*10*1.05,         0.0*0.008]
        # self.Kd = [0.3*10000*873*3*1.025, 0.3*10000*873*3*1.025,  4476*0.3]
        self.Kp = [88318,88318 ,1082*0.06]
        self.Ki = [0.008*10,        0.008*10,         0.0*0.008]
        self.Kd = [6606000, 6606000,  4476*0.3]
        # Output, Error ,Cummulative Error and Previous Error of the PID equation in the form [Long, Lat, Alt]
        self.error = [0.0, 0.0, 0.0]
        self.ouput = [0.0, 0.0, 0.0]
        self.cummulative_error = [0.0, 0.0, 0.0]
        self.previous_error = [0.0, 0.0, 0.0]
        self.max_cummulative_error = [1e-3, 1e-3, 100]
        self.throttle = 0
        self.base_pwm = 1500
        # ----------------------------------------------------------------------------------------------------------

        # Allowed errors in long.,and lat.
        self.allowed_lon_error = 0.0000047487/6
        self.allowed_lat_error = 0.000004517/6

        # Checking if we have to scan or Land
        self.scan = False
        #Variable representing if the box has been grabbed
        self.box_grabbed = 0
        #Constraining the no of times location_error has been called
        self.count = 0
        # Time in which PID algorithm runs
        self.pid_break_time = 0.060  # in seconds
        self.x = 0 

        # Publishing servo-control messaages and altitude,longitude,latitude and zero error on errors /drone_command, /alt_error, /long_error, /lat_error, and current marker id
        self.drone_pub = rospy.Publisher(
            '/drone_command', edrone_cmd, queue_size=1)
        self.alt_error = rospy.Publisher('/alt_error', Float32, queue_size=1)
        self.long_error = rospy.Publisher('/long_error', Float32, queue_size=1)
        self.lat_error = rospy.Publisher('/lat_error', Float32, queue_size=1)
        self.zero_error = rospy.Publisher('/zero_error', Float32, queue_size=1)
        self.curr_m_id = rospy.Publisher(
            '/edrone/curr_marker_id', Int32, queue_size=1)
        self.alt_diff = rospy.Publisher("/alt_diff",Float32, queue_size=1)
        # -----------------------------------------------------------------------------------------------------------

        # Subscribers for gps co-ordinates, and pid_tune GUI, gripper,rangefinder, custom location message and x,y errors in meters
        rospy.Subscriber('/edrone/gps', NavSatFix, self.gps_callback)
        rospy.Subscriber('/pid_tuning_altitude',
                         PidTune, self.altitude_set_pid)
        rospy.Subscriber('/pid_tuning_roll', PidTune, self.long_set_pid)
        rospy.Subscriber('/pid_tuning_pitch', PidTune, self.lat_set_pid)
        rospy.Subscriber('/edrone/location_custom',
                         location_custom, self.scanQR)
        rospy.Subscriber('/edrone/range_finder_bottom',
                         LaserScan, self.range_bottom)
        rospy.Subscriber('/edrone/range_finder_top', LaserScan, self.range_top)
        rospy.Subscriber('/edrone/gripper_check',
                         String, self.gripper_callback)
        rospy.Subscriber('/edrone/err_x_m', Float32, self.handle_x_m_err)
        rospy.Subscriber('/edrone/err_y_m', Float32, self.handle_y_m_err)


    # Callback for getting gps co-ordinates
    def gps_callback(self, msg):
        self.location.altitude = msg.altitude
        self.location.latitude = msg.latitude
        self.location.longitude = msg.longitude
        if self.csv_counter == 0:
            self.get_gps_coordinates()
            self.csv_counter = 1

    # Callback function for /pid_tuning_altitude in case required
    # This function gets executed each time when /tune_pid publishes /pid_tuning_altitude
    def altitude_set_pid(self, alt):
        self.Kp = alt.Kp * 0.06
        self.Ki = alt.Ki * 0.008
        self.Kd = alt.Kd * 0.3

    # Callback function for longitude tuning in case required
    # This function gets executed each time when /tune_pid publishes /pid_tuning_roll
    def long_set_pid(self, long):
        self.Kp[0] = long.Kp * 0.06*1000
        self.Ki[0] = long.Ki * 0.008
        self.Kd[0] = long.Kd * 0.3*10000

    # Callback function for latitude tuning in case required
    # This function gets executed each time when /tune_pid publishes /pid_tuning_pitch
    def lat_set_pid(self, lat):
        self.Kp[1] = lat.Kp * 0.06*1000
        self.Ki[1] = lat.Ki * 0.008*1000
        self.Kd[1] = lat.Kd * 0.3*10000

    # Callback for qr code scanner
    def scanQR(self, msg):
        self.scanned_target[0] = msg.longitude
        self.scanned_target[1] = msg.latitude
        self.scanned_target[2] = msg.altitude
        self.scan = msg.scan
        # print self.scan

    # Callback for bottom rangefinder
    def range_bottom(self, msg):
        self.range_finder_bottom = msg.ranges[0]

    # Callback for top rangefinder
    def range_top(self, msg):
        self.range_finder_top_list = msg.ranges

    # Callback for gripper
    def gripper_callback(self, data):
        if data.data == "True":
            self.gripper_data = True
        else:
            self.gripper_data = False

    def handle_x_m_err(self, msg):
        self.err_x_m = float(msg.data)

    def handle_y_m_err(self, msg):
        self.err_y_m = float(msg.data)

    # Activating the gripper
    def activate_gripper(self, shall_i):
        rospy.wait_for_service('/edrone/activate_gripper')
        act_gripper = rospy.ServiceProxy('/edrone/activate_gripper', Gripper)
        req = GripperRequest(shall_i)
        resp = act_gripper(req)

    # converting latitude to meters
    def lat_to_x(self, input_latitude):
        self.x_lat = 110692.0702932625 * (input_latitude - 19)

    # converting longitude to meters
    def long_to_y(self, input_longitude):
        self.y_long = -105292.0089353767 * (input_longitude - 72)

    def x_to_lat(self):
        return -self.err_x_m/(110692.0702932625)

    def y_to_long(self):
        return self.err_y_m/(-105292.0089353767)

    # ----------------------------------------------------------------------------------------------------------------------

    def pid(self):

        # Error is defined as setpoint minus current orientaion
        self.error[0] = self.location.longitude - \
            self.targets[self.targets_achieved][0]
        self.error[1] = self.location.latitude - \
            self.targets[self.targets_achieved][1]
        self.error[2] = self.location.altitude - \
            self.targets[self.targets_achieved][2]
        
        # if self.error[2] > 5 :
        #     self.error[2] = 5
        # if self.error < -5 and (self.states == 2 or self.states == 5):
        #     self.error = -5 
        max_err_0 = self.previous_error[0]*(self.count==1)
        max_err_0 = max(max_err_0,self.error[0])
        rospy.logdebug("Max error: {}".format(max_err_0)) 
        if abs(self.error[0])>=0.00038256625782:
            rospy.logdebug("long error: {}".format(self.error[0]))
            self.error[0] =(0.000118256625782/3)*math.copysign(1.0,self.error[0])
        # if abs(self.error[1])>0.001/2:
        #     self.error[1] = 0.001/2*math.copysign(1,self.error[1])

        for i in range(3):
            # Cummulative error as sum of previous errors
            self.cummulative_error[i] += self.error[i]
            # Limiting the cummulative error
            if abs(self.cummulative_error[i]) >= self.max_cummulative_error[i]:
                self.cummulative_error[i] = 0.0

        # Main PID Equation i.e assigning the output its value acc. to output = kp*error + kd*(error-previous_error) + ki*cummulative_error
        for i in range(3):
            self.ouput[i] = self.Kp[i] * self.error[i] + self.Ki[i] * \
                self.cummulative_error[i] + self.Kd[i] * \
                (self.error[i]-self.previous_error[i])

        # Contoller handles the states of landing , takeoff, mid-air
        self.controller()
        if self.start_to_check_for_obstacles:
            self.handle_obstacle_x_y()

        # Storing Previous Error values for differential error
        for i in range(3):
            self.previous_error[i] = self.error[i]

        # Setting the throttle that balances the error
        self.drone_cmd.rcThrottle = self.base_pwm - self.ouput[2]

        # CLamping the throttle values between 1000 and 2000
        if self.drone_cmd.rcThrottle > 2000:
            self.drone_cmd.rcThrottle = 2000
        elif self.drone_cmd.rcThrottle < 1010:
            self.drone_cmd.rcThrottle = 1010

        # Publishing the Drone commands for R,P,Y of drone
        self.drone_pub.publish(self.drone_cmd)

        # Publishing errors for plotjuggler
        self.long_error.publish(self.error[0])
        self.lat_error.publish(self.error[1])
        self.alt_error.publish(self.error[2])
        self.zero_error.publish(0.0)
        self.curr_m_id.publish(self.marker_id+1)
    #0:takeoff,1:transverse,2:landing,3:takeoff W/P,4:transverse W/P,5:landing W/P
    def control_state(self,i):
        self.states = i
        
    def controller(self):
        
        rospy.logdebug("Targets_achieved,n,states,x: {},{},{},{}".format(self.targets_achieved, self.n,self.states, self.x))
        self.alt_diff.publish(self.location.altitude-self.buiding_locations[self.marker_id][2])
        # Checking if the drone has reached the nth checkpoint and then incrementing the counter by 1
        # As stated in the problem statement , we have a permissible error of +- 0.05
        if self.location.altitude > self.targets[self.targets_achieved][2] - 1 and self.location.altitude < self.targets[self.targets_achieved][2] + 1 and self.targets_achieved == 0:
            if round(self.previous_error[2], 1) == round(self.error[2], 1) and round(0.2, 1) > abs(self.error[2]):

                # Incrementing the counter of waypoints
                self.targets_achieved += 1
                rospy.logdebug("in takeoff")
                if self.states == 0:
                    #
                    self.control_state(1)
                    self.count = 0
                else:
                    self.control_state(4)
                    self.count = 0

                if self.n < 0:
                    self.n = 0
                    
                # if self.n!=0 and self.states!=5:
                #     self.allowed_lon_error = 0.000047487
                #     self.allowed_lat_error = 0.00004517
                #     print("Error ON")
                #     self.x = 1
                # else :
                #     self.allowed_lon_error = 0.000047487 / 4
                #     self.allowed_lat_error = 0.00004517 / 4
                # Specifying the values for R,P,Y
                self.drone_cmd.rcRoll = self.base_pwm - self.ouput[0]
                self.drone_cmd.rcPitch = self.base_pwm - self.ouput[1]
                self.start_to_check_for_obstacles = True

        # Checking if the drone has reached the lat and long then imcrementing the counter
        # As stated in the problem statement , we have a permissible error of +- self.allowed_lat_error in latitude and +- self.allowed_lon_error in longitude
        elif self.location.latitude > self.targets[self.targets_achieved][1]-self.allowed_lat_error and self.location.latitude < self.targets[self.targets_achieved][1]+self.allowed_lat_error and 0 < self.targets_achieved <= self.n:
            if round(self.previous_error[1], 6) == round(self.error[1], 6) and round(self.allowed_lat_error, 8) > abs(self.error[1]):
                if self.location.longitude > self.targets[self.targets_achieved][0]-self.allowed_lon_error and self.location.longitude < self.targets[self.targets_achieved][0]+self.allowed_lon_error and 0 < self.targets_achieved <= self.n:

                    self.targets_achieved += 1
                    
                    # Specifying the values for R,P,Y
                    self.drone_cmd.rcRoll = self.base_pwm - self.ouput[0]
                    self.drone_cmd.rcPitch = self.base_pwm - self.ouput[1]
                    if self.targets_achieved == self.n:
                        if self.states == 1:
                            #Updating the state of the drone from transvering to landing
                            self.control_state(2)
                        elif self.states == 4:
                            #Updating the state of the drone from transvering with package to landing with package
                            self.control_state(5)
                    if self.targets_achieved == self.n-1 and self.states == 2:
                        self.allowed_lon_error = 0.0000047487/4
                        self.allowed_lat_error = 0.000004517/4
                        self.x = 0
                        
                    self.start_to_check_for_obstacles = True
                    # print "Navigating around"
        else:

            # Drone is taking off
            if self.targets_achieved == 0:
                # print "Taking Off."
                self.start_to_check_for_obstacles = False
                # Specifying the values for R,P,Y
                self.takeoff_control()

            # In mid air
            elif self.targets_achieved <= self.n:
                # Specifying the values for R,P,Y
                self.drone_cmd.rcRoll = self.base_pwm - self.ouput[0]
                self.drone_cmd.rcPitch = self.base_pwm - self.ouput[1]

            # If all the waypoints are reached
            elif self.targets_achieved >= self.n+1:
                if self.states == 1:
                    #Updating the state of the drone from takeoff to transversing
                    self.control_state(2)
                elif self.states == 4:
                    #Updating the state of the drone from takeoff with package to tranversing with package 
                    self.control_state(5)
                # Specifying the values for R,P,Y
                if self.targets_achieved != self.n+2:
                    self.drone_cmd.rcRoll = self.base_pwm - self.ouput[0]
                    self.drone_cmd.rcPitch = self.base_pwm - self.ouput[1]
                else:
                    self.drone_cmd.rcRoll = self.base_pwm
                    self.drone_cmd.rcPitch = self.base_pwm 

                # Check if it reached correct location
                if self.location.latitude > self.targets[self.targets_achieved][1]-self.allowed_lat_error and self.location.latitude < self.targets[self.targets_achieved][1]+self.allowed_lat_error:
                    
                    # If gripper is activated
                    if self.bottom_count > 0:
                        rospy.loginfo("Marker reached")

                    if round(self.previous_error[1], 7) == round(self.error[1], 7) and round(self.allowed_lat_error, 8) > abs(self.error[1]):
                        if self.location.longitude > self.targets[self.targets_achieved][0]-self.allowed_lon_error and self.location.longitude < self.targets[self.targets_achieved][0]+self.allowed_lon_error:

                            # Function controls the landing, scanning and gripping of the drop
                            # if self.targets_achieved != self.n+3:
                            self.targets_achieved = self.n+2
                            self.landing_control()

                            # Handling multiple markers
                            if self.box_grabbed == 1 and self.states == 5 and self.buiding_locations[self.marker_id][3] != "RETURN ": 
                                self.handle_marker()

    def handle_marker(self):
        rospy.logdebug("In Handle marker, marker id: {}".format(self.marker_id))
        # Check if errors are within given 0.2 m threshold
        if abs(self.err_x_m) < 0.2 and abs(self.err_y_m) < 0.2 and (self.location.altitude > self.targets[self.targets_achieved][2]-0.05 and self.location.altitude < self.targets[self.targets_achieved][2]+0.05):
            rospy.logdebug("Errors in X and Y in meters are {}, {} ".format(
                self.err_x_m, self.err_y_m))
            
            # If marker id (0,1,2,3,4,5,6) is 6 then it has achieved all the markers
            if self.marker_id == 16:
                rospy.loginfo("All the targets achieved")
                self.landing_control()
                return
            #if marker <6 new target building will be provided
            elif self.marker_id < 16:
                rospy.loginfo("New building")
                self.activate_gripper(shall_i=False)
                self.box_grabbed = 0
                self.bottom_count = 0
                if self.gripper_data:
                    self.marker_id += 1
                    self.set_new_building_as_target()
                    #Updating the state of the drone from landing with package to takeoff
                    self.control_state(0)

        elif abs(self.err_x_m) < 0.2 and abs(self.err_y_m) < 0.2 :
            rospy.logdebug("x err , y err : {},{}".format(self.err_x_m,self.err_y_m))
            rospy.logdebug("self.targets[self.targets_achieved] : {}".format(self.targets[self.targets_achieved]))
            self.targets_achieved = 2
            
        else:
            rospy.loginfo("Navigating Drone to marker position")
            if self.count == 0:
                self.set_location_using_err()
                self.count = 1
            self.drone_cmd.rcRoll = self.base_pwm-self.ouput[0]
            self.drone_cmd.rcPitch = self.base_pwm-self.ouput[1]
            self.drone_cmd.rcYaw = self.base_pwm

    # ------------------------------HANDLING MARKERS-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

    def set_new_building_as_target(self):
        self.delete_inserted()
        self.targets_achieved = 0
        self.targets[0][0] = self.location.longitude
        self.targets[0][1] = self.location.latitude
        self.targets[1][0] = self.buiding_locations[self.marker_id][0]
        self.targets[1][1] = self.buiding_locations[self.marker_id][1]
        self.targets[2][0] = self.buiding_locations[self.marker_id][0]
        self.targets[2][1] = self.buiding_locations[self.marker_id][1]   
        # self.targets[3][0] = self.buiding_locations[self.marker_id][0]
        # self.targets[3][1] = self.buiding_locations[self.marker_id][1]     
        if self.targets[2][2] > self.buiding_locations[self.marker_id][2]:
            # if self.targets[2][2] > 30 :
            #     self.targets[0][2] = self.targets[2][2] + (15 + self.buiding_locations[self.marker_id][2] -30)*(self.buiding_locations[self.marker_id][2] + 10 > 30) + 15*(self.buiding_locations[self.marker_id][2] + 15 < 30) 
            #     self.targets[1][2] = self.targets[2][2] + (15 + self.buiding_locations[self.marker_id][2] -30)*(self.buiding_locations[self.marker_id][2] + 10 > 30) + 15*(self.buiding_locations[self.marker_id][2] + 15 < 30) 
            # else:
            #     self.targets[0][2] = 30 + (15 + self.buiding_locations[self.marker_id][2] -30)*(self.buiding_locations[self.marker_id][2] + 15 > 30)
            #     self.targets[1][2] = 30 + (15 + self.buiding_locations[self.marker_id][2] -30)*(self.buiding_locations[self.marker_id][2] + 15 > 30)
            self.targets[0][2] = self.buiding_locations[self.marker_id][2] + 10
            self.targets[1][2] = self.buiding_locations[self.marker_id][2] + 10 
        else:
            # self.targets[0][2] = self.buiding_locations[self.marker_id][2] + (15)*(self.buiding_locations[self.marker_id][2] + 15 > 30) + (30 - self.buiding_locations[self.marker_id][2])*(self.buiding_locations[self.marker_id][2] + 15 < 30)
            # self.targets[1][2] = self.buiding_locations[self.marker_id][2] + (15)*(self.buiding_locations[self.marker_id][2] + 15 > 30) + (30 - self.buiding_locations[self.marker_id][2])*(self.buiding_locations[self.marker_id][2] + 15 < 30)
            self.targets[0][2] = self.buiding_locations[self.marker_id][2] + 10
            self.targets[1][2] = self.buiding_locations[self.marker_id][2] + 10
        self.targets[2][2] = self.buiding_locations[self.marker_id][2]
        # if self.targets[1][2] - self.targets[3][2] > 15 :
        #     self.targets[2][2] = self.buiding_locations[self.marker_id][2] + 15
        # else :
        #     self.targets[2][2] = self.buiding_locations[self.marker_id][2] + 15
        self.target_list()
        # print(self.targets)
        self.takeoff_control()

    def set_location_using_err(self):
        self.delete_inserted()
        self.targets[0][0] = self.location.longitude
        self.targets[0][1] = self.location.latitude
        self.targets[-2][0] = self.y_to_long()+self.location.longitude
        self.targets[-2][1] = self.x_to_lat()+self.location.latitude
        self.targets[-1][0] = self.y_to_long()+self.location.longitude
        self.targets[-1][1] = self.x_to_lat()+self.location.latitude
        self.targets[-1][2] = self.buiding_locations[self.marker_id][2]+1
        self.target_list()
        self.targets_achieved = 1
        
    # ------------------------------HANDLING OBSTACLES-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

    def handle_obstacle_x_y(self):
        """
        Check if obstacle is occured:
        if yes:
            then recalulate waypoints with safety distance in apptopriate direction
        if no:
            nothing
        """
        front_range_finder_avg = (
            self.range_finder_top_list[0] + self.range_finder_top_list[4])/2

        left = self.range_finder_top_list[3] < 5  and self.range_finder_top_list[3]>3
        right =  self.range_finder_top_list[1] < 5  and self.range_finder_top_list[1]>3
        front = front_range_finder_avg < 4 and front_range_finder_avg > 1

        #handling obstacle for left range finder
        if left and (not right) and (not front):
            # self.obstacle_count += 1
            # if self.obstacle_count > 3:
            rospy.loginfo("Handling obstacle due to left rangefinder")
            self.targets_achieved = 1
            self.provide_current_loc_as_target(-0.8)
                # self.obstacle_count = 3

        #handling obstacle for right range finder
        if right and (not left) and (not front):
            # self.obstacle_count += 1
            # if self.obstacle_count > 0:
            rospy.loginfo("Handling obstacle due to right rangefinder")
            self.targets_achieved = 1
            self.provide_current_loc_as_target(0.8)
                # self.obstacle_count = 3

        #handling obstacle for front range finder
        if front and (not right) and (not left) :
            rospy.loginfo("Handling obstacle due to front rangefinder")
            self.delete_inserted()
            self.targets[0][0] = self.location.longitude+1.5*(self.safe_dist_long)
            self.targets[0][1] = self.location.latitude -self.safe_dist_lat/5
            self.target_list()
            self.targets_achieved = 1

    # Providing current location with safety distance and recalculating the waypoints
    def provide_current_loc_as_target(self,n):
        self.delete_inserted()
        self.targets[0][0] = self.location.longitude + 1.5*self.safe_dist_long
        self.targets[0][1] = self.location.latitude - n*self.safe_dist_lat
        self.target_list()
        self.targets_achieved = 1

    # --------------------------------HANDLING LANDING SCANNING AND GRIPPING-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    def landing_control(self):
        rospy.logdebug("In landing control")
        # checking if the box is scanned
        if self.scan == True and self.states == 2:
            self.targets[self.targets_achieved][2] -= self.range_finder_bottom
            self.drone_cmd.rcRoll = self.base_pwm
            self.drone_cmd.rcPitch = self.base_pwm
            self.drone_cmd.rcYaw = self.base_pwm
            if self.bottom_count == 0:
                rospy.logdebug("Image Scanned. Targets acquired.")
                self.targets[self.targets_achieved][2] -= self.range_finder_bottom

                # checking if the drone is properly aligned for the box to be gripped
                if not self.gripper_data:
                    self.drone_cmd.rcRoll = self.base_pwm
                    self.drone_cmd.rcPitch = self.base_pwm
                    self.drone_cmd.rcYaw = self.base_pwm
                    rospy.logdebug("Waiting to get aligned")
                else:
                    self.activate_gripper(shall_i=True)
                    if self.gripper_data and self.states == 2:
                        self.targets_achieved = 0
                        self.marker_id += 1
                        self.set_new_building_as_target()
                        #Updating the state of the drone from landing to takeoff with package
                        self.control_state(3)
                        self.bottom_count = 1
                        self.box_grabbed = 1
        elif self.buiding_locations[self.marker_id][3] == "RETURN " and self.states == 5:
            self.targets[self.targets_achieved][2] -= self.range_finder_bottom 
            self.drone_cmd.rcRoll = self.base_pwm
            self.drone_cmd.rcPitch = self.base_pwm
            self.drone_cmd.rcYaw = self.base_pwm
            if self.location.altitude-self.buiding_locations[self.marker_id][2] < 1:
                self.activate_gripper(shall_i=False)
                self.box_grabbed = 0
                self.bottom_count = 0
                self.marker_id += 1
                self.set_new_building_as_target()
                #Updating the state of the drone from landing with package to takeoff
                self.control_state(0)
        # Landing the drone
        else:
            rospy.logdebug("no scan")
            self.drone_cmd.rcRoll = self.base_pwm
            self.drone_cmd.rcPitch = self.base_pwm
            self.drone_cmd.rcYaw = self.base_pwm
            # if self.location.altitude > self.targets[self.targets_achieved][2] - 2 and self.location.altitude < self.targets[self.targets_achieved][2] + 2:
            #     if self.targets_achieved == self.n+2:
            #         self.targets_achieved = self.n+3


        # Changing the allowed error to its maximum once the box is picked up to fast up the drone
        if self.gripper_data:
            self.allowed_lat_error = 0.000004517/2
            self.allowed_lon_error = 0.0000047487/2

        if self.marker_id == 19:
            self.csv_counter == -1
            return

    # ------------------------------HANDLING TAKE OFF-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    def takeoff_control(self):
        # Specifying the values for R,P,Y
        self.drone_cmd.rcRoll = self.base_pwm
        self.drone_cmd.rcPitch = self.base_pwm
        self.drone_cmd.rcYaw = self.base_pwm

    # ----------------------------------------HANDLING WAYPOINTS SUBSTITUTION---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    def delete_inserted(self):
        # Deleting the inserted waypoints
        del self.targets[1:-3]

    def target_refresh(self):
        # Coordinates of 0th new are co-ordinates of last old +- altitude
        self.targets[0][0] = self.targets[2][0]
        self.targets[0][1] = self.targets[2][1]
        self.targets[1][0] = self.scanned_target[1]
        self.targets[1][1] = self.scanned_target[0]
        # self.targets[3][0] = self.scanned_target[1]
        # self.targets[3][1] = self.scanned_target[0]
        self.targets[2][2] = self.scanned_target[2]
        self.target[2][0] = self.scanned_target[1]
        self.target[2][1] = self.scanned_target[0]
        # if self.targets[1][2] - self.targets[3][2] > 15 :
        #     self.targets[2][2] = self.scanned_target[2] + 15
        # else :
        #     self.targets[3][2] = self.scanned_target[2]
        if self.scanned_target[2] > self.targets[0][2]:
            self.targets[0][2] = self.scanned_target[2] + self.offset_alt
            self.targets[1][2] = self.scanned_target[2] + self.offset_alt
        else:
            self.targets[0][2] = self.targets[0][2] + self.offset_alt
            self.targets[1][2] = self.targets[0][2]
        self.target_list()

    def target_list(self):

        # getting the coordinates for current point
        PosX, PosY, alt1 = self.targets[0]

        # getting the coordinates for destiantion point
        ToX, ToY, alt1 = self.targets[1]
        last_alt = self.targets[-1][-1]
        # Finding the distance between them
        dist = math.sqrt(pow((110692.0702932625 * (PosX-ToX)), 2) +
                         pow((-105292.0089353767 * (PosY-ToY)), 2))

        # Defining the number of waypoints to be inserted between current and goal location
        self.n = int(math.floor(dist*self.stride))

        # Initialize list
        points = [[0.0, 0.0, 0.0] for i in range(self.n)]

        x = float(self.n)
        # Finding the waypoints and inserting them into the targets list
        if self.n > 1:
            for i in range(self.n):
                points[i][0] = ((PosX*(1-((i+1)/x))) + ToX*((i+1)/x))
                points[i][1] = ((PosY*(1-((i+1)/x))) + ToY*((i+1)/x))
                points[i][2] = alt1
                self.targets.insert(i+1, points[i][:])
            self.targets[-1][-1] = last_alt

    #Reading coordinates of cells through csv file
    def get_gps_coordinates(self):
        path = rospkg.RosPack().get_path("vitarana_drone")
        path = os.path.join(path,"scripts/manifest.csv")
        # self.targets.append([0.0, 0.0, 0.0])
        deliveries = []
        returns = []
        rows={'1': 72.000142461, '2': 72.000142461 + (0.000014245), '3': 72.000142461 + (2*0.000014245)}
        columns={'A': 18.9998102845, 'B': 18.9998102845 + (0.000013552), 'C': 18.9998102845 + (2*0.000013552)}
        return_rows={'1': 72.000142461, '2': 72.000142461 + (0.000014245), '3': 72.000142461 + (2*0.000014245)}
        return_columns={'X': 18.9999367615, 'Y': 18.9999367615 + (0.000013552), 'Z': 18.9999367615 + (2*0.000013552)}

        #Altitude is constant for all cells since the grid is planar
        altitude=16.757981
        list_of_contents=[]
        lines_count = 0
        with open(path,'r') as file:
            csvreader = csv.reader(file)
            
            #list of rows in csv file
            for row in csvreader:
                lines_count+=1
                rospy.logdebug("CSV: {} {} {}".format(csvreader.line_num,row,lines_count))
                list_of_contents.append(row)
            if lines_count==18:
                rospy.logdebug("CSV reading done")
                # return
                pass
        
        rospy.logdebug("List of contents: {}".format(list_of_contents))
        rospy.logdebug("lenght List of contents: {}".format(len(list_of_contents)))
        for i in range(len(list_of_contents)):
            if list_of_contents[i][0] == "DELIVERY":
                cell = list_of_contents[i][1]
                coordinate = [rows[cell[1]],columns[cell[0]],altitude,list_of_contents[i][0]]
                # rospy.logdebug("Coordinate: {}".format(coordinate))
                self.buiding_locations.append(coordinate)
                # rospy.logdebug("building_locations1: {}".format(self.buiding_locations))
                coordinate = [float(item) for item in list_of_contents[i][2].split(";")]
                z = coordinate[0]
                coordinate[0] = coordinate[1]
                coordinate[1] = z
                coordinate.append(list_of_contents[i][0])
                self.buiding_locations.append(coordinate)
                # rospy.logdebug("building_locations2: {}".format(self.buiding_locations))
                # break
            else: 
                coordinate = [float(item) for item in list_of_contents[i][1].split(";")]
                z = coordinate[0]
                coordinate[0] = coordinate[1]
                coordinate[1] = z
                coordinate.append(list_of_contents[i][0])
                self.buiding_locations.append(coordinate)
                cell = list_of_contents[i][2]
                coordinate = [return_rows[cell[1]],return_columns[cell[0]],altitude,list_of_contents[i][0]]
                self.buiding_locations.append(coordinate)
        self.targets[2] = [self.location.longitude,self.location.latitude,self.location.altitude]   
        self.set_new_building_as_target()
        rospy.logdebug("targets : \n{}".format(self.targets))
        rospy.logdebug("building locations : \n{}".format(self.buiding_locations))
        delivery = []
        returns = []
        for loc in self.buiding_locations:
            if loc[-1] == "DELIVERY":
                delivery.append(tuple(loc[:-1]))
            else :
                returns.append(tuple(loc[:-1]))
        rospy.logdebug("Deliveries: \n{}".format(delivery))
        rospy.logdebug("Returns: \n{}".format(returns))
        # Local helper functions for scheduler
        def calcDistance(x2,y2,x1=72.0002184152,y1=18.9998887669):
            # calculates distance
            dist=math.sqrt(pow(110692.0702932625*(x2-x1),2)+pow(-105292.0089353767*(y2-y1),2))
            
            return dist

        delivery_dict={}
        return_dict={}
        new_targets = []
        def schedular():
            assert(len(delivery)==len(returns))
            for i in range(len(delivery)):
            
                delivery_dict[delivery[i]]=calcDistance(delivery[i][0],delivery[i][1])
                return_dict[returns[i]]=calcDistance(returns[i][0],returns[i][1])
            
            
            sorted_deliveries=dict(OrderedDict(sorted(delivery_dict.items(), key=lambda x: x[1])))
            
            
            sorted_distances=list(sorted_deliveries.values())
            sorted_coordinates=list(sorted_deliveries.keys())
            # print sorted_distances,sorted_coordinates
            delivery_to_return_coordinates=sorted_coordinates[0]
            delivery_to_return_distance=1e100
            print return_dict
            
            for i in delivery:
                for j in returns:
                    current_delivery_to_return_distance=calcDistance(j[0],j[1],i[0],i[1])
                    
                    if current_delivery_to_return_distance < delivery_to_return_distance:
                        
                        delivery_to_return_distance=current_delivery_to_return_distance
                        delivery_to_return_coordinates=j
                path_1=delivery_dict[i]
                # print delivery_to_return_coordinates,return_dict
                path_2=delivery_to_return_distance+return_dict[delivery_to_return_coordinates]
                # break
                #Tolerance = 5 (To maximize distance)
                if path_1 < path_2:
                    print i,path_1,path_2
                    # new_targets.append()
                    #Chooose Path_1- Back to Origin
                    #Pass origin coordiantes
                    
                else:
                    print delivery_to_return_coordinates,path_1,path_2
                    pass
                    #Choose Path_2-Go to return and then proceed 
                    #Pass value stored in delivery_to_return_coordinates
                delivery_to_return_distance=1e100  
        schedular()   
        # sys.exit(0)
    # -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


if __name__ == '__main__':
    # Waiting for Gazebo to start
    # time.sleep(0.5)

    # Creating an instance of the above class
    e_drone = Edrone()

    # PID sampling rate
    r = rospy.Rate(1/e_drone.pid_break_time)
    # try :
    while not rospy.is_shutdown():
        #Condition for calling the pid after the target lists are created
        if e_drone.csv_counter == 1:
            # Call pid function
            # e_drone.pid()
            pass
        # Sleep for specified sampling rate
        r.sleep()
    # except rospy.ROSException as e:
    #     rospy.logdebug("Exiting {}".format(e.message))
