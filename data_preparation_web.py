import uuid
import tqdm
import numpy as np
import cv2
import sys
import os
import math
from talkingface.data.few_shot_dataset import get_image
import shutil
from talkingface.utils import crop_mouth, main_keypoints_index, smooth_array
import json
from mini_live.obj.wrap_utils import index_wrap, index_edge_wrap
import pickle


def step0_keypoints(video_path, out_path):
    Path_output_pkl = video_path + "/circle.pkl"
    with open(Path_output_pkl, "rb") as f:
        pts_3d = pickle.load(f)

    pts_3d = pts_3d.reshape(len(pts_3d), -1)
    smooth_array_ = smooth_array(pts_3d, weight=[0.03, 0.1, 0.74, 0.1, 0.03])
    pts_3d = smooth_array_.reshape(len(pts_3d), 478, 3)

    video_path = os.path.join(video_path, "circle.mp4")
    cap = cv2.VideoCapture(video_path)
    vid_width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)  # 宽度
    vid_height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)  # 高度
    cap.release()
    out_path = os.path.join(out_path, "01.mp4")
    try:
        # 复制文件
        shutil.copy(video_path, out_path)
        print(f"视频已成功复制到 {out_path}")
    except Exception as e:
        print(f"复制文件时出错: {e}")
    return pts_3d,vid_width,vid_height

def step1_crop_mouth(pts_3d, vid_width, vid_height):
    list_source_crop_rect = [crop_mouth(source_pts[main_keypoints_index], vid_width, vid_height) for source_pts in
                             pts_3d]
    list_source_crop_rect = np.array(list_source_crop_rect).reshape(len(pts_3d), -1)
    face_size = (list_source_crop_rect[:,2] - list_source_crop_rect[:,0]).mean()/2.0 + (list_source_crop_rect[:,3] - list_source_crop_rect[:,1]).mean()/2.0
    face_size = int(face_size)//2 * 2
    face_mid = (list_source_crop_rect[:,2:] + list_source_crop_rect[:,0:2])/2.
    # step 1: Smooth Cropping Rectangle Transition
    # Since HTML video playback can have inconsistent frame rates and may not align precisely from frame to frame, adjust the cropping rectangle to transition smoothly, compensating for potential misalignment.
    face_mid = smooth_array(face_mid, weight=[0.10, 0.20, 0.40, 0.20, 0.10])
    face_mid = face_mid.astype(int)
    if face_mid[:, 0].max() + face_size / 2 > vid_width or face_mid[:, 1].max() + face_size / 2 > vid_height:
        raise ValueError("人脸范围超出了视频，请保证视频合格后再重试")

    list_source_crop_rect = np.concatenate([face_mid - face_size // 2, face_mid + face_size // 2], axis = 1)

    # import pandas as pd
    # pd.DataFrame(list_source_crop_rect).to_csv("sss.csv")

    standard_size = 128
    list_standard_v = []
    for frame_index in range(len(list_source_crop_rect)):
        source_pts = pts_3d[frame_index]
        source_crop_rect = list_source_crop_rect[frame_index]
        print(source_crop_rect)
        standard_v = get_image(source_pts, source_crop_rect, input_type="mediapipe", resize=standard_size)

        list_standard_v.append(standard_v)

    return list_source_crop_rect, list_standard_v

def step2_generate_obj(list_source_crop_rect, list_standard_v, out_path):
    from mini_live.obj.obj_utils import generateRenderInfo, generateWrapModel
    render_verts, render_face = generateRenderInfo()
    face_pts_mean = render_verts[:478, :3].copy()

    wrapModel_verts, wrapModel_face = generateWrapModel()
    # 求平均人脸
    from talkingface.run_utils import calc_face_mat
    mat_list, _, face_pts_mean_personal_primer = calc_face_mat(np.array(list_standard_v), face_pts_mean)

    from mini_live.obj.utils import INDEX_MP_LIPS
    face_pts_mean_personal_primer[INDEX_MP_LIPS] = face_pts_mean[INDEX_MP_LIPS] * 0.4 + face_pts_mean_personal_primer[INDEX_MP_LIPS] * 0.6

    from mini_live.obj.wrap_utils import newWrapModel
    face_wrap_entity = newWrapModel(wrapModel_verts, face_pts_mean_personal_primer)

    with open(os.path.join(out_path,"face3D.obj"), "w") as f:
        for i in face_wrap_entity:
            f.write("v {:.3f} {:.3f} {:.3f} {:.02f} {:.0f}\n".format(i[0], i[1], i[2], i[3], i[4]))
        for i in range(len(wrapModel_face) // 3):
            f.write("f {0} {1} {2}\n".format(wrapModel_face[3 * i] + 1, wrapModel_face[3 * i + 1] + 1,
                                             wrapModel_face[3 * i + 2] + 1))
    json_data = []
    for frame_index in range(len(list_source_crop_rect)):
        source_crop_rect = list_source_crop_rect[frame_index]
        standard_v = list_standard_v[frame_index]

        standard_v = standard_v[index_wrap, :2].flatten().tolist()
        mat = mat_list[frame_index].T.flatten().tolist()
        # 将 standard_v 中所有元素四舍五入到两位小数
        standard_v_rounded = [round(i, 5) for i in mat] + [round(i, 1) for i in standard_v]
        print(len(standard_v_rounded), 16 + 209 * 2)
        json_data.append({"rect": source_crop_rect.tolist(), "points": standard_v_rounded})
        # print(json_data)
        # break
    # for frame_index in range(len(list_source_crop_rect)):
    #     source_crop_rect = list_source_crop_rect[frame_index]
    #     standard_v = list_standard_v[frame_index]
    #
    #     standard_v = standard_v[index_wrap, :2].flatten().tolist()
    #     mat = mat_list[frame_index].T.flatten().tolist()
    #     # 将 standard_v 中所有元素四舍五入到两位小数
    #     standard_v_rounded = [round(i, 5) for i in mat]
    #     json_data.append(standard_v_rounded)
    #     # break
    # import pandas as pd
    # pd.DataFrame(json_data).to_csv("sss21.csv")
    # exit()
    with open(os.path.join(out_path, "json_data.json"), "w") as f:
        json.dump(json_data, f)

def step3_generate_ref_tensor(video_path, out_path):
    from talkingface.render_model_mini import RenderModel_Mini
    renderModel_mini = RenderModel_Mini()
    renderModel_mini.loadModel("checkpoint/DINet_mini/epoch_40.pth")

    # 读取ref video信息
    Path_output_pkl = "{}/ref.pkl".format(video_path)
    with open(Path_output_pkl, "rb") as f:
        ref_images_info = pickle.load(f)

    video_path = "{}/ref.mp4".format(video_path)
    cap = cv2.VideoCapture(video_path)
    vid_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    vid_width_ref = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    vid_height_ref = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    list_standard_img_ref = []
    list_standard_v_ref = []
    standard_size = 128
    for frame_index in range(min(vid_frame_count, len(ref_images_info))):
        ret, frame = cap.read()

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
        source_pts = ref_images_info[frame_index]
        source_crop_rect = crop_mouth(source_pts[main_keypoints_index], vid_width_ref, vid_height_ref)

        standard_img = get_image(frame, source_crop_rect, input_type="image", resize=standard_size)
        standard_v = get_image(source_pts, source_crop_rect, input_type="mediapipe", resize=standard_size)
        list_standard_img_ref.append(standard_img)
        list_standard_v_ref.append(standard_v)
    cap.release()

    renderModel_mini.reset_charactor(list_standard_img_ref, np.array(list_standard_v_ref)[:, main_keypoints_index], standard_size = standard_size)

    ref_in_feature = renderModel_mini.net.infer_model.ref_in_feature
    ref_in_feature = ref_in_feature.detach().squeeze(0).cpu().float().numpy().flatten()
    # print(1111, ref_in_feature.shape)

    np.savetxt(os.path.join(out_path, 'ref_data.txt'), ref_in_feature, fmt='%.8f')

def data_preparation_web(path):
    video_path = os.path.join(path, "data")
    out_path = os.path.join(path, "assets")
    os.makedirs(out_path, exist_ok=True)
    pts_3d, vid_width,vid_height = step0_keypoints(video_path, out_path)
    list_source_crop_rect, list_standard_v = step1_crop_mouth(pts_3d, vid_width, vid_height)
    step2_generate_obj(list_source_crop_rect, list_standard_v, out_path)
    step3_generate_ref_tensor(video_path, out_path)

# def main():
#     path = r"video_data/000002"
#     video_path = os.path.join(path, "data")
#     out_path = os.path.join(path, "assets")
#     os.makedirs(out_path, exist_ok=True)
#     pts_3d, vid_width,vid_height = step0_keypoints(video_path, out_path)
#     list_source_crop_rect, list_standard_v = step1_crop_mouth(pts_3d, vid_width, vid_height)
#     step2_generate_obj(list_source_crop_rect, list_standard_v, out_path)
#     step3_generate_ref_tensor(video_path, out_path)
def main():
    # 检查命令行参数的数量
    if len(sys.argv) != 2:
        print("Usage: python data_preparation_web.py <video_dir_path>")
        sys.exit(1)  # 参数数量不正确时退出程序

    # 获取video_name参数
    video_dir_path = sys.argv[1]

    data_preparation_web(video_dir_path)

if __name__ == "__main__":
    main()
