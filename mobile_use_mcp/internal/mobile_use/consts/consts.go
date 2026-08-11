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

package consts

const (
	AuthResultOk         = "success"
	AuthResultErrEmpty   = "err_empty"
	AuthResultErrInvalid = "err_invalid"
)

type MobileUseConfigKey struct{}

type AuthResult struct{}

const (
	ACEPCommandTypeRoot  = "root"
	ACEPCommandTypeShell = "shell"
)

var AndroidKeyEventMap = map[string]int{
	"KEYCODE_BACK": 4,
	"KEYCODE_HOME": 3,
	"KEYCODE_MENU": 82,
}

const (
	AndroidKeyEventBack = "KEYCODE_BACK"
	AndroidKeyEventHome = "KEYCODE_HOME"
	AndroidKeyEventMenu = "KEYCODE_MENU"
)

const (
	ACEPScreenSwipeTimeMs = 300
	ACEPSelectInputMethod = "settings put secure default_input_method \"com.android.inputmethod.pinyin/.PinyinIME\""
	ACEPKeyboardClear     = "am broadcast -a device.gameservice.keyevent.clear"

	ACEPInputTextFormat          = "am broadcast -a device.gameservice.keyevent.value --es value \"$(echo %s | base64 -d)\""
	ACEPCommandScreenTapFormat   = "input tap %d %d"
	ACEPCommandScreenSwipeFormat = "input swipe %d %d %d %d %d"
	ACEPCommandKeyEventFormat    = "input keyevent %d"
	ACEPCommandScreenShotFormat  = "cap_tos -tos_conf \"%s\""
)

const (
	ACEPAppInstallStatusSuccess = 518
)
