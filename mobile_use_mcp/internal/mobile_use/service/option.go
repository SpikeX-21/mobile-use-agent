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

package service

type mobileUseOption struct {
	AccessKey       string
	SecretKey       string
	SessionToken    string
	Host            string
	ProductID       string
	DeviceID        string
	Bucket          string
	Region          string
	Endpoint        string
	TosAccessKey    string
	TosSecretKey    string
	TosSessionToken string
}

type Option func(*mobileUseOption)

func defaultMobileUseOption() *mobileUseOption {
	return &mobileUseOption{
		AccessKey:    "",
		SecretKey:    "",
		SessionToken: "",
		Host:         "open.volcengineapi.com",
	}
}

func WithAccessKey(accessKey string) Option {
	return func(option *mobileUseOption) {
		option.AccessKey = accessKey
	}
}

func WithSecretKey(secretKey string) Option {
	return func(option *mobileUseOption) {
		option.SecretKey = secretKey
	}
}

func WithSessionToken(sessionToken string) Option {
	return func(option *mobileUseOption) {
		option.SessionToken = sessionToken
	}
}

func WithHost(host string) Option {
	return func(option *mobileUseOption) {
		option.Host = host
	}
}

func WithProductID(productID string) Option {
	return func(option *mobileUseOption) {
		option.ProductID = productID
	}
}

func WithDeviceID(deviceID string) Option {
	return func(option *mobileUseOption) {
		option.DeviceID = deviceID
	}
}

func WithBucket(bucket string) Option {
	return func(option *mobileUseOption) {
		option.Bucket = bucket
	}
}

func WithRegion(region string) Option {
	return func(option *mobileUseOption) {
		option.Region = region
	}
}

func WithEndpoint(endpoint string) Option {
	return func(option *mobileUseOption) {
		option.Endpoint = endpoint
	}
}

func WithTosAccessKey(accessKey string) Option {
	return func(option *mobileUseOption) {
		option.TosAccessKey = accessKey
	}
}

func WithTosSecretKey(secretKey string) Option {
	return func(option *mobileUseOption) {
		option.TosSecretKey = secretKey
	}
}

func WithTosSessionToken(sessionToken string) Option {
	return func(option *mobileUseOption) {
		option.TosSessionToken = sessionToken
	}
}
