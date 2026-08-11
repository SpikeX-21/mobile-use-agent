// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// Licensed under the 【火山方舟】原型应用软件自用许可协议
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at 
//     https://www.volcengine.com/docs/82379/1433703
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import { useState, useEffect } from 'react';
import { VePhoneClient, DOM_ID, VePhoneError } from '@/lib/vePhone';
import { cn } from '@/lib/utils/css';
import { useAtom, useAtomValue } from 'jotai';
import { Button } from '@/components/ui/button';
import { VePhoneAtom, PodIdAtom, SessionDataAtom } from '@/app/atom';

enum PhoneState {
  Init = 'init',
  Loading = 'loading',
  Ready = 'ready',
  Error = 'error',
}

const Phone = () => {
  const [podId] = useAtom(PodIdAtom);
  const [vePhone] = useAtom(VePhoneAtom);
  const [state, setState] = useState(PhoneState.Init);
  const [error, setError] = useState<VePhoneError | null>(null);

  const sessionData = useAtomValue(SessionDataAtom);
  const width = sessionData?.pod?.size?.width || 720;
  const height = sessionData?.pod?.size?.height || 1520;

  const [screenRotation, setScreenRotation] = useState('portrait');

  useEffect(() => {
    if (vePhone && podId) {
      vePhone.changePodId(podId);
    }
  }, [podId, vePhone]);

  useEffect(() => {
    if (vePhone) {
      vePhone.on(VePhoneClient.VePhoneEvent.Starting, () => {
        console.log('vephone start');
        setState(PhoneState.Loading);
      });
      vePhone.on(VePhoneClient.VePhoneEvent.StartSuccess, () => {
        console.log('vephone start success');
        setState(PhoneState.Ready);
      });
      vePhone.on(VePhoneClient.VePhoneEvent.Stop, () => {
        console.log('vephone stop');
        setState(PhoneState.Init);
      });
      vePhone.on(VePhoneClient.VePhoneEvent.Destroy, () => {
        console.log('vephone destroy');
        setState(PhoneState.Init);
      });
      vePhone.on(VePhoneClient.VePhoneEvent.StartError, error => {
        console.log('vephone start error', error);
        setError(error as VePhoneError);
        setState(PhoneState.Error);
      });
    }
  }, [vePhone]);

  useEffect(() => {
    if (vePhone) {
      return vePhone.onWithDisposer('on-screen-rotation', (params: any) => {
        console.log('on-screen-rotation', params);
        if (params.appOriginDirection === 'portrait') {
          setScreenRotation('portrait');
        } else {
          setScreenRotation('landscape');
        }
      });
    }
  }, [vePhone]);

  return (
    <div
      className="gap-2 self-stretch flex flex-col justify-center items-center overflow-hidden flex-1"
      style={{
        maxHeight: width / height < 9 / 16 ? '600px' : '500px',
      }}
    >
      <div
        className={cn(
          'bg-[#d8e6fd] rounded-[16px] overflow-hidden border-[6px] border-black relative',
          state !== PhoneState.Ready &&
            "before:content-[''] before:absolute before:top-0 before:left-1/2 before:-translate-x-1/2 before:w-20 before:h-6 before:bg-black before:rounded-b-xl before:z-10",
        )}
        style={
          screenRotation === 'portrait'
            ? {
                flex: 1,
              }
            : {
                width: '100%',
              }
        }
      >
        {(state === PhoneState.Init || state === PhoneState.Loading) && (
          <div className="w-full h-full bg-black/50 flex items-center justify-center">
            <div className="w-12 h-12 rounded-full border-4 border-white border-t-transparent animate-spin" />
          </div>
        )}
        {state === PhoneState.Error && (
          <div className="absolute top-0 left-0 z-10 w-full h-full bg-black/50 flex flex-col items-center justify-center gap-2">
            <div className="text-white">云手机初始化失败</div>
            <div className="bg-black rounded-md p-2 text-white">
              <span>错误码：{error?.errorCode}</span>
            </div>
            <Button
              variant="outline"
              onClick={() => {
                if (vePhone) {
                  vePhone.refresh();
                }
              }}
            >
              重试
            </Button>
          </div>
        )}

        <div
          id={DOM_ID}
          className={cn('max-h-[720px] w-full h-full relative')}
          style={{
            aspectRatio: screenRotation === 'portrait' ? `${width} / ${height}` : `${height} / ${width}`,
          }}
        ></div>
      </div>
    </div>
  );
};

export default Phone;
