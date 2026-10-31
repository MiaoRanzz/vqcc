import unittest
import numpy as np
from dfthcsos_proximal import tangent_prox


class TangentProxTests(unittest.TestCase):
    def test_no_l1_matches_orthogonal_projection(self):
        rng=np.random.default_rng(3);x=rng.normal(size=20);g=rng.normal(size=20);j=rng.normal(size=(3,20))
        step=.3
        y,info=tangent_prox(x,g,np.zeros(20),j,step)
        expected=x-step*(g-j.T@np.linalg.solve(j@j.T,j@g))
        np.testing.assert_allclose(y,expected,atol=1e-10)

    def test_convex_kkt_including_zeroed_and_released_entries(self):
        rng=np.random.default_rng(20261031);zeros=released=0
        for trial in range(30):
            x=rng.normal(size=40)*.1;x[:12]=0
            g=rng.normal(size=40);weights=rng.uniform(.1,1.2,size=40);j=rng.normal(size=(2+trial%2,40));step=.2
            y,info=tangent_prox(x,g,weights,j,step)
            self.assertIsNotNone(y,info)
            np.testing.assert_allclose(j@(y-x),0,atol=1e-9)
            u=j/np.linalg.norm(j,axis=1)[:,None]
            stationarity=(y-x)/step+g-weights*np.sign(x)+u.T@np.array(info['dual'])
            active=y!=0
            np.testing.assert_allclose(stationarity[active]+weights[active]*np.sign(y[active]),0,atol=1e-9)
            self.assertTrue(np.all(np.abs(stationarity[~active])<=weights[~active]+1e-9))
            zeros+=np.count_nonzero((x!=0)&(y==0));released+=np.count_nonzero((x==0)&(y!=0))
        self.assertGreater(zeros,0);self.assertGreater(released,0)


if __name__=='__main__':unittest.main()
