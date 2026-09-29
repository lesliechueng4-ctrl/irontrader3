import { useState } from 'react';
import { App, Button, Dropdown, Form, Input, Modal } from 'antd';
import { KeyOutlined, LogoutOutlined, TeamOutlined, UserOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { post } from '../api/client';
import { useMe } from '../api/hooks';

// 顶栏右上角：当前账号 → 修改密码 / 账号管理（管理员）/ 退出登录
export default function UserMenu() {
  const me = useMe().data;
  const navigate = useNavigate();
  const [pwdOpen, setPwdOpen] = useState(false);
  if (!me?.role) return null;

  const isOwner = me.role === 'owner';
  const items = [
    ...(me.local
      ? []
      : [{ key: 'pwd', icon: <KeyOutlined />, label: '修改密码', onClick: () => setPwdOpen(true) }]),
    ...(isOwner ? [{ key: 'users', icon: <TeamOutlined />, label: '账号管理', onClick: () => navigate('/accounts') }] : []),
    ...(me.local
      ? []
      : [
          { type: 'divider' as const },
          {
            key: 'logout',
            icon: <LogoutOutlined />,
            label: '退出登录',
            onClick: async () => {
              await post('/api/auth/logout').catch(() => undefined);
              window.location.reload();
            },
          },
        ]),
  ];

  return (
    <>
      <Dropdown menu={{ items }} trigger={['click']} placement="bottomRight">
        <Button type="text" className="header-btn header-user" icon={<UserOutlined />}>
          {me.local ? '本机' : me.name}
        </Button>
      </Dropdown>
      {pwdOpen && <ChangePasswordModal onClose={() => setPwdOpen(false)} />}
    </>
  );
}

function ChangePasswordModal({ onClose }: { onClose: () => void }) {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const { message } = App.useApp();

  const submit = async () => {
    const v = await form.validateFields();
    setSaving(true);
    try {
      await post('/api/auth/password', { old_password: v.old_password, new_password: v.new_password });
      message.success('密码已修改；其它设备需要用新密码重新登录');
      onClose();
    } catch (err) {
      message.error((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open title="修改密码" okText="保存" cancelText="取消" onOk={submit} onCancel={onClose} confirmLoading={saving}>
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item name="old_password" label="原密码" rules={[{ required: true, message: '请输入原密码' }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Form.Item
          name="new_password"
          label="新密码"
          rules={[{ required: true, min: 8, message: '至少 8 位' }]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="confirm"
          label="再输一次"
          dependencies={['new_password']}
          rules={[
            { required: true, message: '请再输一次新密码' },
            ({ getFieldValue }) => ({
              validator: (_, value) =>
                !value || value === getFieldValue('new_password') ? Promise.resolve() : Promise.reject(new Error('两次输入不一致')),
            }),
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
