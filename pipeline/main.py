import os
import sys
import time
import socket
import json
import cv2
from datetime import datetime
import logging as log
import paho.mqtt.client as mqtt
import timeit
from collections import deque
from argparse import ArgumentParser
from inference import Network
from openvino_helper import preprocessing,reidentification_preprocess
from sklearn.metrics.pairwise import cosine_similarity
from utility import *
# MQTT server environment variables
HOSTNAME = socket.gethostname()
IPADDRESS = socket.gethostbyname(HOSTNAME)
MQTT_HOST = IPADDRESS
MQTT_PORT = 3001
MQTT_KEEPALIVE_INTERVAL = 60
FONT = cv2.FONT_HERSHEY_PLAIN
ALPHA=0.9
log.root.setLevel(log.NOTSET)
streaming_enabled=True

def build_argparser():
    """
    Parse command line arguments.
    :return: command line arguments
    """
    parser = ArgumentParser()
    parser.add_argument("-m", "--model", required=True, type=str,
                        help="Path to an xml file with a trained model.")
    parser.add_argument("-i", "--input", required=True, type=str,
                        help="Path to image or video file")
    parser.add_argument("-si", "--show_info", required=False, type=bool, default=True,
                        help="Show Extra Information on camera image")
    parser.add_argument("-msg", "--message", required=False, type=str, default="",
                        help="Message to show on image frame")
    parser.add_argument("-l", "--cpu_extension", required=False, type=str,
                        default=None,
                        help="MKLDNN (CPU)-targeted custom layers."
                             "Absolute path to a shared library with the"
                             "kernels impl.")
    parser.add_argument("-d", "--device", type=str, default="CPU",
                        help="Specify the target device to infer on: "
                             "CPU, GPU, FPGA or MYRIAD is acceptable. Sample "
                             "will look for a suitable plugin for device "
                             "specified (CPU by default)")
    parser.add_argument("-pt", "--prob_threshold", type=float, default=0.3,
                        help="Probability threshold for detections filtering"
                        "(0.5 by default)")

    parser.add_argument("-rim", "--reident_model", type=str, default=None,
                        help="Provide model for reidentification")
    return parser


def connect_mqtt():
    ### TODO: Connect to the MQTT client ###
    client = mqtt.Client()
    client.on_message = on_message
    client.on_connect = on_connect
    client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE_INTERVAL)
    client.subscribe("settings/streaming")
    client.loop_start()
    return client
def on_connect(self, client, userdata, flags, rc):
    log.info("MQTT connected: result code=%i", rc)    

def on_message(client, userdata, message):
    global streaming_enabled
    text = message.payload.decode("utf-8")
    dt = json.loads(str(text))
    streaming_enabled=dt['result']

def reidentification(id,networkReIdentification, crop_person, identification_input_shape, total_unique_persons, conf):
    log.Logger(str(identification_input_shape))
    idetification_frame = reidentification_preprocess(crop_person, net_input_shape=identification_input_shape)
    networkReIdentification.exec_network(id,idetification_frame)
    if networkReIdentification.wait(id) == 0:
        ident_output = networkReIdentification.get_output(id)
        for i in range(len(ident_output)):
            if (len(total_unique_persons) == 0):
                total_unique_persons.append(ident_output[i].reshape(1, -1))
            else:
                newFound = True
                detected_person = ident_output[i].reshape(1, -1)
                for index in range(len(total_unique_persons)):  # checking that detected person is in out list or not
                    similarity = cosine_similarity(detected_person, total_unique_persons[index])[0][0]
                    if similarity > 0.65: #0.58
                        newFound = False
                        total_unique_persons[index] = detected_person  # updating detetected one
                        break

                if newFound and conf > 0.90:
                    total_unique_persons.append(detected_person)
        return total_unique_persons



def infer_on_stream(args, client):
    """
    Initialize the inference network, stream video to network,
    and output stats and video.
    :param args: Command line arguments parsed by `build_argparser()`
    :param client: MQTT client
    :return: None
    """
    global streaming_enabled
    # Initialise the class
    infer_network = Network()




    total_unique_persons = []
    use_reidentification=False
    # Set Probability threshold for detections
    if not args.prob_threshold is None:
        prob_threshold = args.prob_threshold
    else:
        prob_threshold = 0.2
        
    cur_request_id = 0
    last_detection_time=None
    duration=0
        
    start = None
    
    single_image_mode = False
    show_info =False
    if args.show_info:
        show_info = args.show_info
    message = None
    if args.message:    
        message = args.message
    
    if args.input == 'CAM':
        input_stream = 0
    elif args.input.endswith('.jpg') or args.input.endswith('.bmp')or args.input.endswith('.png'):
        single_image_mode = True
        input_stream = args.input
    # Checks for video file
    else:
        input_stream = args.input
        assert os.path.isfile(args.input), "Specified input file doesn't exist"

    ### TODO: Load the model through `infer_network` ###
    n, c, h, w = infer_network.load_model(args.model, args.device, 1, 1,
                                          cur_request_id, args.cpu_extension)[1]

    # Intialize class for reidentification
    networkReIdentification =None
    identification_input_shape = None

    if args.reident_model:
        networkReIdentification = Network()
        networkReIdentification.load_model(args.reident_model, args.device, 1, 1,cur_request_id, args.cpu_extension)
        identification_input_shape = networkReIdentification.get_input_shape()
        use_reidentification= True

    ### TODO: Handle the input stream ###
    if not single_image_mode:
        cap = cv2.VideoCapture(input_stream)
        if input_stream:
            cap.open(args.input)
        if not cap.isOpened():
            log.error("ERROR! Unable to open video source")

        detection_frame_count=0
        total_frame_count =0
        previous_detection_time=None
        last_person_counts = []
        average_person_count =0
        detection_time = None

        total_seconds_elapsed_for_detection=0

        # Parameters for duration
        max_len = 40
        track_threshold = 0.2 
        track  = deque(maxlen=max_len)

        ### TODO: Loop until stream is over ###
        while cap.isOpened():
            ### TODO: Read from the video capture ###
            flag, frame = cap.read()
            if not flag:
                break
            
            ### TODO: Pre-process the image as needed ###
            image = preprocessing(frame, h, w)

            ### TODO: Start asynchronous inference for specified request ###
            inf_start = time.time()
            
            infer_network.exec_network(cur_request_id, image)
            ### TODO: Wait for the result ###
            output_img = frame
            if infer_network.wait(cur_request_id) == 0:
                ### TODO: Get the results of the inference request ###
                det_time = time.time() - inf_start
                result = infer_network.get_output(cur_request_id)
                
                ### TODO: Extract any desired stats from the results ###

                image_h, image_w, _ = frame.shape
                num_detections = 0
                for box in result[0][0]:
                    label   = box[1]
                    conf    = box[2]
                    
                    if label == 1:
                        if(conf>prob_threshold):
                            x_min   = int(box[3]* image_w)
                            y_min   = int(box[4]*image_h)
                            x_max   = int(box[5]*image_w)
                            y_max   = int(box[6]*image_h)
                            dist=(y_max-y_min)/(y_min+y_max);
                            color = (0,dist*255,255-dist*255)
                            if use_reidentification:
                                try:
                                    if conf >0.85:
                                        crop_person = frame[y_min:y_max, x_min:x_max]

                                        total_unique_persons = reidentification(cur_request_id,networkReIdentification, crop_person,
                                                                                identification_input_shape, total_unique_persons, conf)
                                except Exception as err:
                                    pass


                            cv2.rectangle(frame,(x_min,y_min), (x_max, y_max),color, int(1))
                            num_detections +=1
                            last_detection_time = datetime.now()
                            if start is None:
                                start = time.time()
                                time.clock()
                    else:
                        label_box_pos=None        
                    if last_detection_time is not None:
                        second_diff = (datetime.now() - last_detection_time).total_seconds()
                        if second_diff >= 1.5:
                            if start is not None and num_detections == 0:
                                elapsed = time.time() - start
                                client.publish("person/duration", json.dumps({"duration": elapsed}))
                                start = None
                                last_detection_time = None

                person_counts=num_detections

                overlay = output_img.copy()
                if show_info:
                    cv2.putText(overlay,
                            message,
                            (10,40),
                            FONT, 1,
                            (250, 250, 250),
                            2,
                            cv2.LINE_AA)
                    cv2.putText(overlay,
                            'Person[s] found: {}'.format(person_counts),
                            (10,overlay.shape[0]-40),
                            FONT, 1,
                            (255, 255, 255),
                            1,
                            cv2.LINE_AA)
                    cv2.putText(overlay,
                            str(datetime.now().strftime("%A, %d. %B %Y %I:%M:%S %p")),
                            (10,overlay.shape[0]-20),
                            FONT, 1,
                            (250, 250, 250),
                            1,
                            cv2.LINE_AA)
                    cv2.addWeighted(overlay, ALPHA, output_img, 1 - ALPHA, 0, output_img)              
           

            if len(last_person_counts)>10:
                last_person_counts = last_person_counts[1:len(last_person_counts)-1]
            last_person_counts.append(person_counts)

            average_person_count =int(sum(last_person_counts)/len(last_person_counts))



            client.publish("person", json.dumps({"count": str(person_counts), "total": len(total_unique_persons)}))
                     

            ### TODO: Send the frame to the FFMPEG server ###
            if streaming_enabled:
                sys.stdout.buffer.write(output_img)
                sys.stdout.flush()
                pass
        if cap:
            cap.release()
            cv2.destroyAllWindows()
            client.disconnect()
            infer_network.dispose()

    ### TODO: Write an output image if `single_image_mode` ###
    elif single_image_mode:
        frame = cv2.imread(input_stream)
        image = preprocessing(frame, h, w)
        infer_network.exec_network(0, image)
        if infer_network.wait(0) == 0:
            result = infer_network.get_output(0)
            output_img, person_counts = get_draw_boxes_on_image(
                        result, frame, prob_threshold,True)
            cv2.imwrite('output_image.jpg', output_img)




def main():
    """
    Load the network and parse the output.
    :return: None
    """
    # Grab command line args
    args = build_argparser().parse_args()
    # Connect to the MQTT server
    client = connect_mqtt()
    # Perform inference on the input stream
    infer_on_stream(args, client)


if __name__ == '__main__':
    main()
    exit(0)
