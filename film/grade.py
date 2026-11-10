import numpy as np, sys, os
from PIL import Image, ImageFilter
BLACK=[(0,(0,0,0)),(.18,(7,9,13)),(.45,(44,50,60)),(.72,(135,146,162)),(.9,(216,223,233)),(1,(247,249,252))]
def ramp(l):
    st=BLACK if os.environ.get('GRADE')=='black' else [(0,(0,6,28)),(.18,(2,22,78)),(.45,(14,62,150)),(.72,(86,140,215)),(.9,(205,222,245)),(1,(247,249,252))]
    xs=[s[0] for s in st]; out=np.zeros(l.shape+(3,))
    for c in range(3): out[...,c]=np.interp(l,xs,[s[1][c] for s in st])
    return out
def grade(im, seed=1):
    a=np.asarray(im.convert('RGB'),dtype=np.float32)/255
    l=(a@np.array([.3,.59,.11]))
    l=np.clip((l-.02)/.8,0,1)**.82                      # lift highlights, keep a deep shadow floor
    bl=np.asarray(Image.fromarray((l*255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(10)),dtype=np.float32)/255
    l=np.clip(l+.35*np.maximum(bl-.55,0),0,1)            # halation around the lights
    out=ramp(l)/255
    h,w=l.shape; rng=np.random.default_rng(seed)
    g=rng.normal(0,1,(h,w)).astype(np.float32); g=np.asarray(Image.fromarray(((g*40)+128).clip(0,255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(.6)),dtype=np.float32)/255-.5
    p=rng.normal(0,1,(h//3,w//3)).astype(np.float32); p=np.asarray(Image.fromarray(((p*50)+128).clip(0,255).astype(np.uint8)).resize((w,h),Image.BICUBIC).filter(ImageFilter.GaussianBlur(2.5)),dtype=np.float32)/255-.5
    yy,xx=np.mgrid[0:h,0:w]; v=1-.55*(((xx-w/2)/(w/2))**2+((yy-h/2)/(h/2))**2)/2
    out=out*(1+.55*g[...,None]*(.4+.6*(1-l)[...,None]*0+.6))*(1+.18*p[...,None])*v[...,None]
    return Image.fromarray((out.clip(0,1)*255).astype(np.uint8))
if __name__=='__main__':
    grade(Image.open(sys.argv[1])).save(sys.argv[2])
