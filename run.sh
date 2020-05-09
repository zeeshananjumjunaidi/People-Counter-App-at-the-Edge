# Important otherwise openvino might try to use latest installed python version.
python_version=3.5
# This is for debugging purpose only. to stop this script press ctrl + z 
# first run a without it and make sure it is working fine
KEEP_RUNNING=false
# 640x480 for camera
#INPUT="CAM"
X=854
Y=480
# 854x480 for traffic.mp4
INPUT="resources/traffic.mp4"
#INPUT="resources/image_1.png"
# To render extra info overlay on top of output image frame.
SHOWINFO=true
# MESSAGE text will appear on top most of the screen.
MESSAGE="[Udacity]"
# Threshold for the detection confidence.
THRESHOLD=0.1
# Sourcing openvino
source /opt/intel/openvino/bin/setupvars.sh
# location of model .xml file, keep the .bin (weight & biases) file in the same directory 
# as app'll try to load it from the same directory.
MODEL="model/output/ssd_mobilenet_v2_coco_2018_03_29/frozen_inference_graph.xml"
# print output
echo "*************"
echo "INPUT: " $INPUT
echo "MODEL: " $MODEL
echo "*************"
# Running detection pipeline for images if input path ends with any of the given image format otherwise 
# we'll conside it as video stream and output it to ffmpeg server.
if [[ $INPUT == *.png ]] || [[ $INPUT == *.jpg ]] || [[ $INPUT == *.jpeg ]] || [[ $INPUT == *.bpm ]]; then
echo "running pipeline for image sequences"
python3.5 pipeline/main.py -si $SHOWINFO --message $MESSAGE -i $INPUT -m $MODEL -pt $THRESHOLD  
else
echo "running pipeline for video streaming..."
if [[ $KEEP_RUNNING == true ]];then
    while(true);
    do
        python3.5 pipeline/main.py -si $SHOWINFO --message $MESSAGE -i $INPUT -m $MODEL -pt $THRESHOLD   | ffmpeg -v warning -f rawvideo -pixel_format bgr24 -video_size "$X"x$Y -framerate 24 -i - http://0.0.0.0:3004/fac.ffm
    done
else
        python3.5 pipeline/main.py -si $SHOWINFO --message $MESSAGE -i $INPUT -m $MODEL -pt $THRESHOLD   | ffmpeg -v warning -f rawvideo -pixel_format bgr24 -video_size "$X"x$Y -framerate 24 -i - http://0.0.0.0:3004/fac.ffm
fi

fi
