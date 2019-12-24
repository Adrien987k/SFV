"""
Renders mesh using pytorch-NMR for visualization.
Directly renders with the same (weird) orthographic proj of HMR
(no perspective).
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import cv2
import neural_renderer as nr
import numpy as np
import torch
from torch.autograd import Variable
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

from skimage.io import imread

# from src.pytorch_util.torch_utils import orthographic_proj_withz_idrot
# import src.util.renderer as vis_util

from src.exp_scripts.scale_trans import compute_opt_cam_with_vis
from .torch_utils import orthographic_proj_withz_idrot
from ..util import renderer as vis_util
from ..datasets.common import resize_img


colors = {
    # colorblind/print/copy safe:
    'blue': [0.65098039, 0.74117647, 0.85882353],
    'pink': [.9, .7, .7],
    'mint': [ 166/255.,  229/255.,  204/255.],
    'mint2': [ 202/255.,  229/255.,  223/255.],
    'green': [ 153/255.,  216/255.,  201/255.],
    'green2': [ 171/255.,  221/255.,  164/255.],
    'red': [ 251/255.,  128/255.,  114/255.],
    'orange': [ 253/255.,  174/255.,  97/255.],
    'yellow': [ 250/255.,  230/255.,  154/255.]
}


def get_dims(x):
    return x.dim() if isinstance(x, torch.Tensor) else x.ndim


class VisRenderer(object):
    """
    Utility to render meshes using pytorch NMR
    faces are F x 3 or 1 x F x 3 numpy
    this is for visualization only -- does not allow backprop.
    This class assumes all inputs are Torch/numpy variables.
    This renderer expects quarternion rotation for camera,,
    """

    def __init__(self,
                 img_size=256,
                 face_path='src/tf_smpl/smpl_faces.npy',
                 t_size=1):

        self.renderer = nr.Renderer(
            img_size, camera_mode='look_at', perspective=False)
        self.set_light_dir([1, .5, -1], int_dir=0.3, int_amb=0.7)
        self.set_bgcolor([1, 1, 1.])
        self.img_size = img_size

        self.faces_np = np.load(face_path).astype(np.int)
        self.faces = asVariable(torch.IntTensor(self.faces_np).cuda())
        if self.faces.dim() == 2:
            self.faces = torch.unsqueeze(self.faces, 0)

        # Default color:
        default_tex = np.ones((1, self.faces.shape[1], t_size, t_size, t_size,
                               3))
        self.default_tex = asVariable(torch.FloatTensor(default_tex).cuda())

        # Default camera:
        cam = np.hstack([0.9, 0, 0])
        default_cam = asVariable(torch.FloatTensor(cam).cuda())
        self.default_cam = torch.unsqueeze(default_cam, 0)

        # Setup proj fn:
        self.proj_fn = orthographic_proj_withz_idrot

    def __call__(self,
                 verts,
                 cam=None,
                 texture=None,
                 rend_mask=False,
                 alpha=False,
                 img=None,
                 color_name='blue'):
        """
        verts is |V| x 3 numpy/cuda torch Variable or B x V x 3
        cams is 3D [s, tx, ty], numpy/cuda torch Variable or B x 3
        cams is NOT the same as OpenDR renderer.
        Directly use the cams of HMR output
        Returns N x N x 3 numpy, where N is the image size.
        Or B x N x N x 3 when input was batched

        if you're using this as a batch, make sure you send in B x 3 cameras
        as well as B x * x * x 3 images if you're using it.
        """
        num_batch = 1

        if get_dims(verts) == 3 and verts.shape[0] != 1:
            print('batch mode')
            num_batch = verts.shape[0]
            # Make sure everything else is also batch mode.
            if cam is not None:
                assert get_dims(cam) == 2 and cam.shape[0] == num_batch
            if img is not None:
                assert img.ndim == 4 and img.shape[0] == num_batch

        if texture is None:
            # single color.
            color = torch.FloatTensor(colors[color_name]).cuda()
            texture = color * self.default_tex
            texture = texture.repeat(num_batch, 1, 1, 1, 1, 1)
        else:
            texture = asFloatTensor(texture)
            if texture.dim() == 5:
                # Here input it F x T x T x T x 3 (instead of F x T x T x 3)
                # So add batch dim.
                texture = torch.unsqueeze(texture, 0)
        if cam is None:
            cam = self.default_cam
            if num_batch > 1:
                cam = cam.repeat(num_batch, 1)
        else:
            cam = asFloatTensor(cam)
            if cam.dim() == 1:
                cam = torch.unsqueeze(cam, 0)

        verts = asFloatTensor(verts)
        if verts.dim() == 2:
            verts = torch.unsqueeze(verts, 0)

        verts = asVariable(verts)
        cam = asVariable(cam)
        texture = asVariable(texture)

        # set offset_z for persp proj
        proj_verts = self.proj_fn(verts, cam, offset_z=0)
        # Flipping the y-axis here to make it align with
        # the image coordinate system!
        proj_verts[:, :, 1] *= -1

        # Adjust for batch.
        faces = self.faces.repeat(num_batch, 1, 1)
        if rend_mask:
            rend = self.renderer.render_silhouettes(proj_verts, faces)
            rend = torch.unsqueeze(rend, 0)
            rend = rend.repeat(1, 3, 1, 1)
        else:
            rend = self.renderer.render(proj_verts, faces, texture)

        rend = rend.data.cpu().numpy().transpose((0, 2, 3, 1))
        rend = np.clip(rend, 0, 1) * 255.0

        # Make sure rendered img & the projected verts are the same:
        # import matplotlib.pyplot as plt
        # plt.ion()
        # plt.figure(1)
        # plt.clf()
        # plt.imshow(rend.astype(np.uint8))
        # test = proj_verts[0].data.cpu().numpy()
        # # 'unflip'
        # test[:, 1] *= -1
        # test = (test + 1) * 0.5 * self.renderer.image_size
        # plt.scatter(test[::100, 0], test[::100, 1])
        # import ipdb; ipdb.set_trace()
        if num_batch == 1:
            rend = rend[0]

        if not rend_mask and (alpha or img is not None):
            mask = self.renderer.render_silhouettes(proj_verts, faces)
            mask = mask.data.cpu().numpy()
            if img is not None:
                mask = np.repeat(np.expand_dims(mask, 3), 3, axis=3)
                if num_batch == 1:
                    mask = mask[0]
                # TODO: Make sure img is [0, 255]!!!
                return (img * (1 - mask) + rend * mask).astype(np.uint8)
            else:
                return self.make_alpha(rend, mask)
        else:
            return rend.astype(np.uint8)

    def rotated(self,
                verts,
                deg,
                axis='y',
                cam=None,
                texture=None,
                rend_mask=False,
                alpha=False,
                color_name='blue'):
        """
        vert is N x 3, torch FloatTensor (or Variable)
        """
        import cv2
        if axis == 'y':
            axis = [0, 1., 0]
        elif axis == 'x':
            axis = [1., 0, 0]
        else:
            axis = [0, 0, 1.]

        new_rot = cv2.Rodrigues(np.deg2rad(deg) * np.array(axis))[0]
        new_rot = asFloatTensor(new_rot)

        verts = asFloatTensor(verts)

        # TODO for later:
        # Get the batch size.
        # Then make new_row also unsqueeze, and repeat by num_batch

        if get_dims(verts) == 2:
            # Make it in to 1 x N x 3
            verts = verts.unsqueeze(0)
        num_batch = verts.shape[0]

        new_rot = new_rot.unsqueeze(0)
        new_rot = new_rot.repeat(num_batch, 1, 1)

        center = verts.mean(1, keepdim=True)
        centered_v = (verts - center)
        new_verts = torch.matmul(new_rot, centered_v.permute(0, 2, 1)).permute(0, 2, 1) + center


        return self.__call__(
            new_verts,
            cam=cam,
            texture=texture,
            rend_mask=rend_mask,
            alpha=alpha,
            color_name=color_name
        )

    def make_alpha(self, rend, mask):
        rend = rend.astype(np.uint8)
        alpha = (mask * 255).astype(np.uint8)

        imgA = np.dstack((rend, alpha))
        # import matplotlib.pyplot as plt
        # plt.ion()
        # plt.figure(1)
        # plt.clf()
        # plt.imshow(imgA)
        return imgA

    def set_light_dir(self, direction, int_dir=0.8, int_amb=0.8):
        self.renderer.light_direction = direction
        self.renderer.light_intensity_directional = int_dir
        self.renderer.light_intensity_ambient = int_amb

    def set_bgcolor(self, color):
        self.renderer.background_color = color


def asVariable(x):
    if type(x) is not torch.autograd.Variable:
        x = Variable(x, requires_grad=False)
    return x


def asFloatTensor(x):
    if isinstance(x, np.ndarray):
        x = torch.FloatTensor(x).cuda()
    # ow assumed it's already a Tensor..
    return x


def convert_as(src, trg):
    src = src.type_as(trg)
    if src.is_cuda:
        src = src.cuda(device=trg.get_device())
    if type(trg) is torch.autograd.Variable:
        src = Variable(src, requires_grad=False)
    return src


def visualize_img(img,
                  cam,
                  kp_pred,
                  vert,
                  renderer,
                  kp_gt=None,
                  text={},
                  rotated_view=False,
                  mesh_color='blue',
                  pad_vals=None,
                  no_text=False):
    """
    Visualizes the image with the ground truth keypoints and
    predicted keypoints on left and image with mesh on right.

    Keypoints should be in normalized coordinates, not image coordinates.

    Args:
        img: Image.
        cam (3x1): Camera parameters.
        kp_gt: Ground truth keypoints.
        kp_pred: Predicted keypoints.
        vert: Vertices.
        renderer: SMPL renderer.
        text (dict): Optional information to include in the image.
        rotated_view (bool): If True, also visualizes mesh from another angle.
        if pad_vals (2,) is not None, removes those values from the image
            (undo img pad to make square)
    Returns:
        Combined image.
    """
    img_size = img.shape[0]
    text.update({'sc': cam[0], 'tx': cam[1], 'ty': cam[2]})
    if kp_gt is not None:
        gt_vis = kp_gt[:, 2].astype(bool)
        loss = np.sum((kp_gt[gt_vis, :2] - kp_pred[gt_vis])**2)
        text['kpl'] = loss

    # Undo pre-processing.
    # Make sure img is [0-255]
    input_img = ((img + 1) * 0.5) * 255.
    rend_img = renderer(vert, cam=cam, img=input_img, color_name=mesh_color)
    if not no_text:
        rend_img = vis_util.draw_text(rend_img, text)

    # Draw skeletons
    pred_joint = ((kp_pred + 1) * 0.5) * img_size
    skel_img = vis_util.draw_skeleton(input_img, pred_joint)
    if kp_gt is not None:
        gt_joint = ((kp_gt[:, :2] + 1) * 0.5) * img_size
        skel_img = vis_util.draw_skeleton(
            skel_img, gt_joint, draw_edges=False, vis=gt_vis)

    if pad_vals is not None:
        skel_img = remove_pads(skel_img, pad_vals)
        rend_img = remove_pads(rend_img, pad_vals)
    if rotated_view:
        rot_img = renderer.rotated(
            vert, 90, cam=cam, alpha=False, color_name=mesh_color)
        if pad_vals is not None:
            rot_img = remove_pads(rot_img, pad_vals)

        return skel_img / 255, rend_img / 255, rot_img / 255

    else:
        return skel_img / 255, rend_img / 255


def visualize_img_orig(cam, kp_pred, vert, renderer, start_pt, scale,
                       proc_img_shape, im_path=None, img=None,
                       rotated_view=False, mesh_color='blue', max_img_size=300,
                       no_text=False, bbox=None, crop_cam=None):
    """
    Visualizes the image with the ground truth keypoints and predicted keypoints
    in the original image space (squared).

    If you get out of memory error, make max_img_size smaller.

    Args:
       must supply either the im_path or img
       start_pt, scale, proc_img_shape are parameters used to preprocess the
       image.

       scale_result is how much to scale the current image

    Returns:
        Combined image.
    """
    if img is None:
        img = imread(im_path)
        # Pre-process image to [-1, 1] bc it expects this.
        img = ((img / 255.) - 0.5) * 2
    if np.max(img.shape[:2]) > max_img_size:
        # if the image is too big it wont fit in gpu and nmr poops out.
        scale_orig = max_img_size / float(np.max(img.shape[:2]))
        img, _ = resize_img(img, scale_orig)
        undo_scale = (1. / np.array(scale)) * scale_orig
    else:
        undo_scale = 1. / np.array(scale)

    if bbox is not None:
        assert(crop_cam is not None)
        img = img[bbox[0]:bbox[1], bbox[2]:bbox[3]]
        # For these, the cameras are already adjusted.
        scale = 1.
        start_pt = np.array([0, 0])

    # NMR needs images to be square..
    img, pad_vals = make_square(img)
    img_size = np.max(img.shape[:2])
    renderer.renderer.image_size = img_size

    # Adjust kp_pred.
    # This is in 224x224 cropped space.
    pred_joint = ((kp_pred + 1) * 0.5) * proc_img_shape[0]
    # This is in the original image.
    pred_joint_orig = (pred_joint + start_pt - proc_img_shape[0]) * undo_scale

    # in normalize coord of the original image:
    kp_orig = 2 * (pred_joint_orig / img_size) - 1
    if bbox is not None:
        use_cam = crop_cam
    else:
        # Convert cam into cam that projects into the normalized coord of the orig
        # image. This is what it projects to now.
        # x_crop_norm = cam[0] * (vert[::10, :2] + cam[1:])
        # x_crop = (x_crop_norm + 1) * 0.5 * proc_img_shape[0]
        # x_orig = (x_crop + start_pt - proc_img_shape[0]) * undo_scale
        # # We want camera s.t. it gives you this.
        # x_orig_norm = 2 * (x_orig / img_size) - 1

        # This is camera in crop image coord.
        cam_crop = np.hstack([proc_img_shape[0] * cam[0] * 0.5,
                              cam[1:] + (2./cam[0]) * 0.5])
        # Test:
        # x_crop_test = cam_crop[0] * (vert[::10, :2] + cam_crop[1:])
        # assert(np.linalg.norm(x_crop_test - x_crop) < 1e-5)

        # This is camera in orig image coord
        cam_orig = np.hstack([
            cam_crop[0] * undo_scale,
            cam_crop[1:] + (start_pt - proc_img_shape[0]) / cam_crop[0]
        ])
        # Test:
        # x_orig_test = cam_orig[0] * (vert[::10, :2] + cam_orig[1:])
        # assert(np.linalg.norm(x_orig_test - x_orig) < 1e-5)

        # This is the camera in normalized orig_image coord
        new_cam = np.hstack([
            cam_orig[0] * (2. / img_size),
            cam_orig[1:] - (1 / ((2./img_size) * cam_orig[0]))
        ])
        new_cam = new_cam.astype(np.float32)
        # Test:
        # x_orig_norm_test = new_cam[0] * (vert[::10, :2] + new_cam[1:])
        # x_orig_test = (x_orig_norm_test + 1) * 0.5 * img_size
        # assert(np.linalg.norm(x_orig_norm_test - x_orig_norm) < 1e-5)

        # import matplotlib.pyplot as plt
        # plt.ion()
        # plt.clf()
        # # plt.imshow((crop + 1) * 0.5)
        # # plt.scatter(pred_joint[:, 0], pred_joint[:, 1])
        # plt.imshow((img + 1) * 0.5)
        # plt.scatter(pred_joint_orig[:, 0], pred_joint_orig[:, 1])
        # plt.scatter(x_orig_test[:, 0], x_orig_test[:, 1])
        # plt.draw()
        # plt.pause(1e-3)
        # import ipdb; ipdb.set_trace()
        use_cam = new_cam

    # Call visualize_img with this camera:
    rendered_orig = visualize_img(
        img=img,
        cam=use_cam,
        kp_pred=kp_orig,
        vert=vert,
        renderer=renderer,
        rotated_view=rotated_view,
        mesh_color=mesh_color,
        pad_vals=pad_vals,
        no_text=no_text,
    )
    # import matplotlib.pyplot as plt
    # plt.ion()
    # plt.clf()
    # plt.imshow(rendered_orig)
    # plt.draw()
    # plt.pause(1e-3)
    # import ipdb; ipdb.set_trace()

    return rendered_orig


def visualize_mesh_og(cam, vert, renderer, start_pt, scale, proc_img_shape,
                      im_path=None, img=None, deg=0, mesh_color='blue',
                      max_img_size=300, pad=50, crop_cam=None, bbox=None):
    """
    Visualize mesh in original image space.

    If you get out of memory error, make max_img_size smaller.


    If crop_cam and bbox is not None,
    crops the image and uses the crop_cam to render.
    (See compute_video_bbox.py)
    """
    if img is None:
        img = imread(im_path)
        # Pre-process image to [-1, 1] bc it expects this.
        img = ((img / 255.) - 0.5) * 2

    if bbox is not None:
        assert(crop_cam is not None)
        img = img[bbox[0]:bbox[1], bbox[2]:bbox[3]]
        # For these, the cameras are already adjusted.
        scale = 1.
        start_pt = np.array([0, 0])
    if np.max(img.shape[:2]) > max_img_size:
        # if the image is too big it wont fit in gpu and nmr poops out.
        scale_orig = max_img_size / float(np.max(img.shape[:2]))
        img, _ = resize_img(img, scale_orig)
        undo_scale = (1. / np.array(scale)) * scale_orig
    else:
        undo_scale = 1. / np.array(scale)
    # NMR needs images to be square..
    img, pad_vals = make_square(img)
    img_size = np.max(img.shape[:2])
    renderer.renderer.image_size = img_size

    if bbox is not None:
        # test= renderer.rotated(
        #     verts=vert,
        #     deg=deg,
        #     cams=crop_cam,
        #     color_name=mesh_color,
        # )
        # import matplotlib.pyplot as plt
        # plt.ion()
        # plt.clf()
        # plt.imshow(test)
        # plt.draw()
        # plt.pause(1e-3)
        # import ipdb; ipdb.set_trace()
        return renderer.rotated(
            verts=vert,
            deg=deg,
            cam=crop_cam,
            color_name=mesh_color,
        )
    else:
        # This is camera in crop image coord.
        cam_crop = np.hstack([proc_img_shape[0] * cam[0] * 0.5,
                              cam[1:] + (2./cam[0]) * 0.5])

        # This is camera in orig image coord
        cam_orig = np.hstack([
            cam_crop[0] * undo_scale,
            cam_crop[1:] + (start_pt - proc_img_shape[0]) / cam_crop[0]
        ])

        # This is the camera in normalized orig_image coord
        new_cam = np.hstack([
            cam_orig[0] * (2. / img_size),
            cam_orig[1:] - (1 / ((2./img_size) * cam_orig[0]))
        ])
        new_cam = new_cam.astype(np.float32)

        return renderer.rotated(
            verts=vert,
            deg=deg,
            cam=new_cam,
            color_name=mesh_color,
        )


def make_square(img):
    """
    Bc nmr only deals with square image, adds pad to the shorter side.
    """
    img_size = np.max(img.shape[:2])
    pad_vals = img_size - img.shape[:2]

    img = np.pad(
        array=img,
        pad_width=((0, pad_vals[0]), (0, pad_vals[1]), (0, 0)),
        mode='constant'
    )

    return img, pad_vals


def remove_pads(img, pad_vals):
    """
    Undos padding done by make_square.
    """

    if pad_vals[0] != 0:
        img = img[:-pad_vals[0], :]
    if pad_vals[1] != 0:
        img = img[:, :-pad_vals[1]]

    return img


def draw_skeleton_3d(skel):
    """
    Draws a simple 3D skeleton.

    Args:
        skel ({25, 14, 19}x3).

    Returns:
        Image.
    """
    edges = [
        # right leg
        (0, 1),
        (1, 2),
        # left leg
        (3, 4),
        (4, 5),
        # right arm
        (6, 7),
        (7, 8),
        # left arm
        (9, 10),
        (10, 11),
        # head
        (12, 13),
        # spine
        (12, 3),
        (12, 2),
        (12, 9),
        (12, 8),
    ]
    fig = plt.figure(figsize=(10, 10))
    ax = fig.add_subplot(111, projection='3d')

    x = skel[:, 0]
    z = -skel[:, 1]
    y = skel[:, 2]
    ax.scatter(x, y, z)

    for i, j in edges:
        ax.plot([x[i], x[j]], [y[i], y[j]], [z[i], z[j]])

    ax.set_xlim(-1, 1)
    ax.set_ylim(-1, 1)
    ax.set_zlim(-1, 1)
    fig.canvas.draw()
    data = np.frombuffer(fig.canvas.tostring_rgb(), dtype=np.uint8)
    data = data.reshape(fig.canvas.get_width_height()[::-1] + (3,))
    plt.close()
    return data


def compute_video_bbox(cams, kps, joints, proc_infos, margin=10, renderer=None, verts=None, degrees=None):
    """
    Given the prediction and original image info,
    figures out the min/max extent (bbox)
    of the person in the entire video.

    Adjust the cameras so now ppl project in this new bbox.
    Needed to crop the video around the person and also to
    rotate the mesh.

    cams: N x 3, predicted camera
    joints: N x K x 3, predicted 3D joints for debug
    kp: N x K x 3, predicted 2D joints to figure out extent

    proc_infos: dict holding:
       start_pt, scale: N x 2, N x 1
         preprocessing done on this image.
    im_shape: image shape after preprocessing

    im_path: to the first image to figure out size of orig video
    """
    im_path = proc_infos[0]['im_path']
    img = imread(im_path)
    img_h, img_w = img.shape[:2]
    img_size = np.max([img_h, img_w])

    im_shape = proc_infos[0]['im_shape'][0]

    new_cams = []
    bboxes = []
    # For each image, get the joints in the original coord frame:
    for i, (proc_info, kp, cam) in enumerate(zip(proc_infos, kps, cams)):
        scale = proc_info['scale']
        start_pt = proc_info['start_pt']

        undo_scale = 1. / np.array(scale)
        # Adjust kp_pred.
        # This is in 224x224 cropped space.
        pred_joint = ((kp + 1) * 0.5) * im_shape
        # This is in the original image.
        pred_joint_orig = (pred_joint + start_pt - im_shape) * undo_scale
        # in normalize coord of the original image:
        # kp_orig = 2 * (pred_joint_orig / img_size) - 1
        # This is camera in crop image coord (224x224).
        cam_crop = np.hstack([im_shape * cam[0] * 0.5,
                              cam[1:] + (2./cam[0]) * 0.5])
        # This is camera in orig image coord
        cam_orig = np.hstack([
            cam_crop[0] * undo_scale,
            cam_crop[1:] + (start_pt - im_shape) / cam_crop[0]
        ])
        # This is the camera in normalized orig_image coord
        new_cam = np.hstack([
            cam_orig[0] * (2. / img_size),
            cam_orig[1:] - (1 / ((2./img_size) * cam_orig[0]))
        ])
        new_cams.append(new_cam.astype(np.float32))

        # Test:
        # x_crop_norm = cam[0] * (joints[i][:, :2] + cam[1:])
        # x_crop = (x_crop_norm + 1) * 0.5 * im_shape
        # x_orig = (x_crop + start_pt - im_shape) * undo_scale
        # x_orig_norm = 2 * (x_orig / img_size) - 1
        # x_orig_norm_test = new_cam[0] * (joints[i][:, :2] + new_cam[1:])
        # x_orig_test = (x_orig_norm_test + 1) * 0.5 * img_size
        # assert(np.linalg.norm(x_orig_norm_test - x_orig_norm) < 1e-5)
        # import ipdb; ipdb.set_trace()
        # # Crop image at this bbox.
        # img_here = imread(proc_info['im_path'])
        # img_sc, _ = resize_img(img_here, scale)
        # img_sc_pad = np.pad(img_sc, ((224,), (224,), (0,)), 'edge')
        # crop = img_sc_pad[start_pt[1]:start_pt[1]+im_shape, start_pt[0]:start_pt[0]+im_shape]
        # import matplotlib.pyplot as plt
        # plt.ion()
        # plt.subplot(211)
        # skel_img_orig = vis_util.draw_skeleton(img_here, x_orig)
        # plt.imshow(skel_img_orig)
        # plt.subplot(212)
        # skel_img = vis_util.draw_skeleton(crop, x_crop)
        # plt.imshow(skel_img)
        # Figure out the bbox:
        # K x 2
        x = pred_joint_orig[:, 0]
        y = pred_joint_orig[:, 1]
        ymin = max(0, min(y) - margin)
        ymax = min(img_h - 1, max(y) + margin)
        xmin = max(0, min(x) - margin)
        xmax = min(img_w - 1, max(x) + margin)
        bbox = np.array([ymin, ymax, xmin, xmax])

        bboxes.append(bbox)

    # Figure out the video level bbox.
    # bbox is in format [ymin, ymax, xmin, xmax]
    bboxes = np.stack(bboxes)
    bbox = np.array([
        np.min(bboxes[:, 0]),
        np.max(bboxes[:, 1]),
        np.min(bboxes[:, 2]),
        np.max(bboxes[:, 3])
    ])
    bbox = bbox.astype(np.int)
    # Now adjust the cams by this bbox offset.
    ymin, xmin = bbox[0], bbox[2]
    new_offset = np.array([xmin, ymin])
    new_offset_norm = np.linalg.norm(new_offset)
    img_size_crop = np.max([bbox[1] - bbox[0], bbox[3] - bbox[2]])


    # Rotated images: save delta translation
    new_cams_cropped = []
    # rot_x = proc_infos[0]['start_pt'][0] - (new_offset[0] * scale)
    # rot0 = proc_infos[0]['start_pt'] - (new_offset * scale)

    for i, (proc_info, kp, cam) in enumerate(zip(proc_infos, kps, cams)):
        scale = proc_info['scale']

        undo_scale = 1. / np.array(scale)
        start_pt0 = proc_info['start_pt']

        start_pt = start_pt0 - (new_offset * scale)

        if np.linalg.norm(proc_info['start_pt']) < new_offset_norm:
            print('crop is more than start pt..?')
            import ipdb; ipdb.set_trace()

        # This is camera in crop image coord (224x224).
        cam_crop = np.hstack([im_shape * cam[0] * 0.5,
                              cam[1:] + (2./cam[0]) * 0.5])

        # This is camera in orig image coord
        cam_orig = np.hstack([
            cam_crop[0] * undo_scale,
            cam_crop[1:] + (start_pt - im_shape) / cam_crop[0]
        ])
        # cam_orig_rot = np.hstack([
        #     cam_crop[0] * undo_scale,
        #     cam_crop[1:] + (start_pt_crop - im_shape) / cam_crop[0]
        # ])

        # This is the camera in normalized orig_image coord
        new_cam = np.hstack([
            cam_orig[0] * (2. / img_size_crop),
            cam_orig[1:] - (1 / ((2./img_size_crop) * cam_orig[0]))
        ])
        new_cams_cropped.append(new_cam.astype(np.float32))

        # new_cam_rot = np.hstack([
        #     cam_orig_rot[0] * (2. / img_size_crop),
        #     cam_orig_rot[1:] - (1 / ((2./img_size_crop) * cam_orig_rot[0]))
        # ])
        # new_cams_cropped_rot.append(new_cam_rot.astype(np.float32))

        # Test:
        # x_crop_norm = cam[0] * (joints[i][:, :2] + cam[1:])
        # x_crop = (x_crop_norm + 1) * 0.5 * im_shape
        # x_orig = (x_crop + start_pt - im_shape) * undo_scale
        # x_orig_norm = 2 * (x_orig / img_size) - 1
        # x_orig_norm_test = new_cam[0] * (joints[i][:, :2] + new_cam[1:])
        # x_orig_test = (x_orig_norm_test + 1) * 0.5 * img_size

        # # Crop image at this bbox.
        # img_here = imread(proc_info['im_path'])
        # crop = img_here[bbox[0]:bbox[1], bbox[2]:bbox[3]]
        # import matplotlib.pyplot as plt
        # plt.ion()
        # plt.subplot(211)
        # plt.imshow(img_here)
        # plt.subplot(212)
        # skel_img_crop = vis_util.draw_skeleton(crop, x_orig)
        # plt.imshow(skel_img_crop)
        # renderer.renderer.image_size = np.max(crop.shape[:2])
        # test = renderer(verts=verts[i], cams=new_cam, color_name='blue')
        # plt.subplot(211)
        # plt.imshow(test)
        # plt.draw()
        # plt.pause(1e-3)
        # import ipdb; ipdb.set_trace()
        # assert(np.linalg.norm(x_orig_norm_test - x_orig_norm) < 1e-5)

    """        
    # Now compute offsets for new_cams_cropped_rot.
    f = 5
    new_trans_rot = []
    # [s, tx, ty]
    for i, cam_crop in enumerate(new_cams_cropped):
        tz = f / cam_crop[0]
        txty = cam_crop[1:]
        if i > 0:
            trans_rot = np.hstack([txty, tz]) - new_trans_rot[0]
            # go back to original
            # import ipdb; ipdb.set_trace()
            # test = trans_rot + new_trans_rot[0]
            # sc = f / test[-1]
            # np.hstack([sc, test[:2]])
        else:
            # Just keep this untouched.
            trans_rot = np.hstack([txty, tz])
        new_trans_rot.append(trans_rot)

    cam_rots = []
    for deg in degrees:
        cam_here = []
        aangle = np.deg2rad(int(deg)) * np.array([0, 0, 1])
        R = cv2.Rodrigues(aangle)[0]
        for i, trans_rot in enumerate(new_trans_rot):
            if i > 0:
                # Rotate and add back original
                trans = R.dot(trans_rot) + new_trans_rot[0]
                # trans = trans_rot + new_trans_rot[0]
            else:
                trans = trans_rot
            # Convert it back to [s, tx, ty]
            sc = f / trans[-1]
            cam_rot = np.hstack([sc, trans[:2]])
            cam_here.append(cam_rot)

        cam_rots.append(cam_here)

    return bbox, new_cams_cropped, cam_rots
    """
    return bbox, new_cams_cropped


def get_params_from_omega(smpl_model, regressor, omega, cam=None):
    cam = omega[:3] if cam is None else cam
    pose = omega[3:3 + 72]
    shape = omega[75:]
    smpl_model.pose[:] = pose
    smpl_model.betas[:] = shape
    verts = np.copy(smpl_model.r)
    joints = regressor.dot(verts)
    kps = cam[0] * (joints[:, :2] + cam[1:])
    return {
        'cam': cam,
        'joints': joints,
        'kps': kps,
        'pose': pose,
        'shape': shape,
        'verts': verts,
    }


def draw_omega(smpl_model, renderer, regressor, omega, image, cam=None,
               color='blue', kps_gt=None, text={}):
    """
    Draws mesh over image.

    Args:
        omega (85).
        image (NxHxWx3).
        cam (3).
        color (str).
        kps_gt (25x3).

    Returns:
        Image.
    """
    params = get_params_from_omega(smpl_model, regressor, omega, cam)
    kps_pred = params['kps']
    joints = params['joints']
    verts = params['verts']
    if kps_gt is not None:
        kps_pred, cam = compute_opt_cam_with_vis(
            got=joints[:, :2],
            want=kps_gt[:, :2],
            vis=kps_gt[:, 2],
        )
    rend_img = visualize_img(
        img=image,
        cam=cam,
        kp_pred=kps_pred,
        vert=verts,
        renderer=renderer,
        kp_gt=kps_gt,
        mesh_color=color,
        text=text,
    )
    return np.hstack(rend_img)


if __name__ == '__main__':
    from smpl_webuser.serialization import load_model
    SMPL_MODEL_PATH = 'models/neutral_smpl_with_cocoplus_reg.pkl'
    face_path = "src/tf_smpl/smpl_faces.npy"
    model = load_model(SMPL_MODEL_PATH, MODIFIED=False)
    model.pose[0] = np.pi

    verts = np.copy(model.r)

    renderer = VisRenderer(face_path=face_path)

    img = np.random.rand(renderer.img_size, renderer.img_size, 3) * 255.
    img = img.astype(np.uint8)

    rend = renderer(verts, cam=np.array([1., 0.1, 0.15]), img=img)
    rend_rot = renderer.rotated(verts, 90, cam=np.array([1., 0.1, 0.15]))
    # Old renderer
    from ..util.renderer import SMPLRenderer
    renderer2 = SMPLRenderer(face_path=face_path)
    rend2 = renderer2(verts + np.array([0, 0, 6]))

    import matplotlib.pyplot as plt
    plt.ion()
    plt.figure(1)
    plt.clf()
    plt.subplot(221)
    plt.imshow(rend)
    plt.title('Pytorch-NMR renderer')
    plt.subplot(222)
    plt.imshow(rend2)
    plt.title('OpenDR renderer')
    plt.subplot(223)
    plt.imshow(rend_rot)
    plt.title('Pytorch-NMR rotated')
    # import ipdb
    # ipdb.set_trace()

    # Batch render:
    # random pertubation
    model.pose[10] = np.pi
    verts2 = np.copy(model.r)
    img2 = np.random.rand(renderer.img_size, renderer.img_size, 3) * 255.
    img2 = img2.astype(np.uint8)

    all_verts = np.stack((verts, verts2))
    all_cams = np.stack((np.array([.6, 0.1, 0.15]), np.array([.9, -0.1, .15])))
    all_imgs = np.stack((img, img2))

    rends = renderer(all_verts, cam=all_cams, img=all_imgs)
    rend_rots = renderer.rotated(all_verts, 90, cam=all_cams)

    plt.figure(2)
    plt.clf()
    plt.subplot(211)
    plt.imshow(np.hstack(rends))
    plt.title('batch rendered')
    plt.subplot(212)
    plt.imshow(np.hstack(rend_rots))
    plt.title('batch rendered rot')

    # Test we can do single after batch
    rend0 = renderer(verts, cam=np.array([1., 0.1, 0.15]), img=img)
    import ipdb; ipdb.set_trace()
