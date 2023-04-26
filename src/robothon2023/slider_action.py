#!/usr/bin/env python3
import tf
import rospy
import numpy as np
import math 
from kortex_driver.msg import TwistCommand, CartesianReferenceFrame

from robothon2023.abstract_action import AbstractAction
from robothon2023.full_arm_movement import FullArmMovement
from geometry_msgs.msg import PoseStamped, Quaternion, Twist, Vector3
from robothon2023.transform_utils import TransformUtils
from utils.kinova_pose import KinovaPose, get_kinovapose_from_pose_stamped
from utils.force_measure import ForceMeasurmement

class SliderAction(AbstractAction):

    def __init__(self, arm: FullArmMovement, transform_utils: TransformUtils):
        super().__init__(arm, transform_utils)
        self.arm = arm
        self.fm = ForceMeasurmement()
        self.tf_utils = transform_utils
        self.listener = tf.TransformListener()
        self.slider_pose = PoseStamped()
        
        self.cartesian_velocity_pub = rospy.Publisher('/my_gen3/in/cartesian_velocity', TwistCommand, queue_size=1)
      

    def pre_perceive(self) -> bool:
        print ("in pre perceive")

        print("Getting slider pose")
        self.get_slider_pose()
        return True

    def act(self) -> bool:
        print ("in act")

        rospy.loginfo(">> Moving arm to slider <<")
        if not self.move_arm_to_slider():
            return False

        rospy.loginfo(">> Clossing gripper <<")
        if not self.arm.execute_gripper_command(0.45):
            return False

        rospy.loginfo(">> Approaching slider with caution <<")
        if not self.approach_slider_with_caution():
            return False

        rospy.loginfo(">> Clossing gripper <<")
        if not self.arm.execute_gripper_command(0.75):
            return False

        rospy.loginfo(">> Moving arm along the slider <<")
        if not self.move_arm_along_slider(direction="forward"):
            return False

        rospy.loginfo(">> Stopping arm <<")
        if not self.stop_arm():
            return False

        rospy.loginfo(">> Moving slider back  <<")
        if not self.move_arm_along_slider(direction="backward"):
            return False

        rospy.loginfo(">> Stopping arm <<")
        if not self.stop_arm():
            return False

        rospy.loginfo(">> open gripper <<")
        if not self.arm.execute_gripper_command(0.50):
            return False

        rospy.loginfo(">> Retract arm back <<")
        if not self.retract_arm_back():
            return False

        rospy.loginfo(">> Stopping arm <<")
        if not self.stop_arm():
            return False

        rospy.loginfo(">> Process finished successfully <<")

        return True

    def verify(self) -> bool:
        print ("in verify")

        ## can be verified by checking the current location of the EEF 
        return True

    def do(self) -> bool:

        success = True
        
        success &= self.pre_perceive()
        success &= self.act()
        success &= self.verify()

        return success


    def tooltip_pose_callback(self, msg):
        self.tooltip_pose_z_with_base = msg.base.tool_pose_z


    def move_arm_to_slider(self):
        """
        Move arm to along slider in with velocity vector
        """

        offset = 0.08
        rospy.loginfo("slider pose below")
        print(self.slider_pose)
        slider_pose = self.rotate_Z_down(self.slider_pose)
        pose_to_send = get_kinovapose_from_pose_stamped(slider_pose)
        pose_to_send.z += offset # add 10 cm to the z axis and then approach the slider

        success = self.arm.send_cartesian_pose(pose_to_send)
        if not success:
            return False
        return True

    def approach_slider_with_caution(self):
        """
        Approach slider with caution
        """

        offset = 0.05 # offset for the distance from tool frame to the tool tip
        rate_loop = rospy.Rate(10)
        self.fm.set_force_threshold(force=[4,4,3]) # force in z increases to 4N when it is in contact with the board

        # enable force monitoring
        self.fm.enable_monitoring()
        
        # calculate velocity
        distance = offset; time = 3 # move 5 cm in 6 seconds
        velocity = distance/time

        # create twist command to move towards the slider
        approach_twist = TwistCommand()
        approach_twist.reference_frame = CartesianReferenceFrame.CARTESIAN_REFERENCE_FRAME_TOOL
        approach_twist.twist.linear_z = velocity

        while not self.fm.force_limit_flag and not rospy.is_shutdown(): 
            # check for force limit flag and stop if it is true
            # check for the z axis of the tooltip and stop if it is less than 0.111(m) (the z axis of the slider) from base frame

            if self.fm.force_limit_flag:
                break
            self.cartesian_velocity_pub.publish(approach_twist)
            rate_loop.sleep()

        success = self.stop_arm()
        if not success:
            return False
        
        self.fm.disable_monitoring()

        distance = 0.01 ; time = 1 # move back 8 mm
        velocity = distance/time

        retract_twist = TwistCommand()
        retract_twist.reference_frame = CartesianReferenceFrame.CARTESIAN_REFERENCE_FRAME_TOOL
        retract_twist.twist.linear_z = -velocity
        if self.fm.force_limit_flag:
            self.cartesian_velocity_pub.publish(retract_twist)
            rospy.sleep(time)
        
        self.stop_arm()
        return True


    def move_arm_along_slider(self, direction : str = "None"):
        """
        Move arm along slider 
        """

        if direction == "forward":
            dv = 1
            distance = 0.0255
        elif direction == "backward":
            dv = -1
            distance = 0.0255
        elif direction == "None":
            print("No direction specified")
            return False
        else:
            print("Invalid direction")
            return False
        
        #calculate force in slider axis 

        # #get current yaw angle 
        # current_pose = self.arm.get_current_pose()
        # force_theta = current_pose.theta_z_deg

        # #calcuate mag in given angle        
        # slider_force_threshold = 3 # N
        # theta = np.deg2rad(force_theta)

        # force_x = max( abs(slider_force_threshold * math.cos(theta)) , 2.5)
        # force_y = max( abs(slider_force_threshold * math.sin(theta)) , 2.5)

        # print("force_x: ", force_x)
        # print("force_y: ", force_y)
        
        success = self.arm.move_down_with_caution(distance = dv*distance, time = 3,
                                force_threshold=[5,5,3], approach_axis='x',
                                retract = False,
                                retract_dist = 0.01) 
        if not success:
            return False
        
        rospy.loginfo(">> moved slider forward <<")
        rospy.loginfo(">> SLEEPING for 0.5 <<")

        rospy.sleep(0.5)
        return True

    def retract_arm_back(self):
        """
        Move arm back using twist command
        """
        retract_velocity = 0.04 # m/s
        retract_twist_cmd = TwistCommand()
        retract_twist_cmd.reference_frame = CartesianReferenceFrame.CARTESIAN_REFERENCE_FRAME_TOOL
        retract_twist_cmd.twist.linear_z = -retract_velocity # neg velocity for upwards movement
        self.cartesian_velocity_pub.publish(retract_twist_cmd)
        rospy.sleep(1.5)
        return True

    def stop_arm(self):
        """
        Stop arm by sending zero velocity
        """

        velocity_vector = TwistCommand()
        velocity_vector.reference_frame = CartesianReferenceFrame.CARTESIAN_REFERENCE_FRAME_MIXED # for proper joypad control
        self.cartesian_velocity_pub.publish(velocity_vector)
        return True

    def get_slider_pose(self):
        """
        Get slider pose
        """
        msg = PoseStamped()
        msg.header.frame_id = "slider_start_link"
        msg.header.stamp = rospy.Time(0)
        self.slider_pose = self.transform_utils.transformed_pose_with_retries(msg, "base_link")

        return True

    def rotate_Z_down(self, msg: PoseStamped) -> PoseStamped:

        msg = msg
        msg.header.stamp = rospy.Time.now()

        # quaternion to euler for given pose
        e = list(tf.transformations.euler_from_quaternion([msg.pose.orientation.x, msg.pose.orientation.y, msg.pose.orientation.z, msg.pose.orientation.w]))

        rot_eluer = [math.pi, 0.0,math.pi]  # rotate 180 degrees around x axis to make the z pointing (down) and the y will be in opposite direction than original and we 
        # add 180 around z axis to set the orientation of camera facing the gui screen 

        e[0] += rot_eluer[0]
        e[1] += rot_eluer[1]
        e[2] += rot_eluer[2]

        q = list(tf.transformations.quaternion_from_euler(e[0], e[1], e[2]))

        msg.pose.orientation = Quaternion(*q)
        msg = self.transform_utils.transformed_pose_with_retries(msg, 'base_link')
        return msg




    def garr(self):

        time = 4.5 # s
        slider_velocity = round(distance/time , 3) # m/s

        slider_velocity_cmd = TwistCommand()
        slider_velocity_cmd.reference_frame = CartesianReferenceFrame.CARTESIAN_REFERENCE_FRAME_TOOL
        slider_velocity_cmd.twist.linear_x = slider_velocity * dv

        rate_loop = rospy.Rate(10)

        self.fm.reset_force_limit_flag()
        self.fm.set_force_threshold(force=[3.0,3.0,3.0]) 
        self.fm.enable_monitoring() 

        # stop the while loop after 3 seconds
        start_time = rospy.get_time()
        while not self.fm.force_limit_flag and not rospy.is_shutdown() and (rospy.get_time() - start_time) < time: 
            if self.fm.force_limit_flag:
                rospy.loginfo(">> Force limit flag stopped the action <<")
                break
            self.cartesian_velocity_pub.publish(slider_velocity_cmd)
            rate_loop.sleep()

        success = self.stop_arm()
        if not success:
            return False
        
        self.fm.disable_monitoring()

        distance = 0.01 ; time = 0.5 # move back 8 mm
        velocity = distance/time

        retract_twist = TwistCommand()
        retract_twist.reference_frame = CartesianReferenceFrame.CARTESIAN_REFERENCE_FRAME_TOOL
        retract_twist.twist.linear_x = -velocity * dv

        self.cartesian_velocity_pub.publish(retract_twist)
        rospy.sleep(time)
        self.stop_arm()




















