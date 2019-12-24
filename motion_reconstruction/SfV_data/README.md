This directory contains data and results used in the paper:

SFV: Reinforcement Learning of Physical Skills from Videos
Transactions on Graphics (Proc. ACM SIGGRAPH Asia 2018)
Xue Bin Peng, Angjoo Kanazawa, Jitendra Malik, Pieter Abbeel, Sergey Levine
University of California, Berkeley


The original videos are in `original_video/`.

`data/` contains for each video:
- .mp4 (HMR-smoothed, 3D human reconstruction results)
- .bvh (output of HMR-smoothed in bvh format)
- .h5 (output of HMR-smoothed and openpose)

The bvh files contains the subset of SMPl joints used for training the
character.

The mp4 files are visualizations of the HMR-smoothed results. It shows:
Top Left: Recovered mesh overlayed
Top Center: From a different view
Top Right: Results of OpenPose
Bottom Left: Input video
Bottom Center: 2D joint reprojection of the recovered 3D mesh

The h5 files contain a dictionary of frame_id with a list of detections for each
person:
`{frame_id, list of person}`
Each `person` is a dict with keys:
```
'cams', 'joints', 'op_kp', 'verts', 'joints3d', 'theta', 'proc_param'
```

- `op_kp` is the 18 keypoint detection from openpose.
- `cams`, `joints`, `op_kp`, `verts`, `joints3d`, `theta` are HMR outputs after
smoothing.
- `proc_param` is a dictionary containing the bounding box params. See `scale`
  an `start_pt`. Each frame is scaled using `scale` and then 224x224 crop was
  made from the `start_pt`.



# Reference
If you found this data helpful, please cite:
```
@article{
	2018-TOG-SFV,
	author = {Peng, Xue Bin and Kanazawa, Angjoo and Malik, Jitendra and Abbeel, Pieter and Levine, Sergey},
	title = {SFV: Reinforcement Learning of Physical Skills from Videos},
	journal = {ACM Trans. Graph.},
	volume = {37},
	number = {6},
	month = nov,
	year = {2018},
	articleno = {178},
	numpages = {14},
	publisher = {ACM},
	address = {New York, NY, USA},
	keywords = {physics-based character animation, computer vision, video imitation, reinforcement learning, motion reconstruction}
	}
```
