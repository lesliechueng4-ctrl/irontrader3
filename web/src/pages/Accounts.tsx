import { useState } from 'react';
import { Alert, App, Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Typography } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { get, post, send } from '../api/client';
import { useIsOwner, useMe } from '../api/hooks';

interface Account {
  username: string;
  display_name: string;
  role: 'owner' | 'member';
  disabled: boolean;
  note?: string;
  password?: string; // 只在新建 / 重置时返回一次
}

const ROLE_LABEL = { owner: '管理员', member: '成员' } as const;

/** 给对方的登录信息（管理员复制后发微信） */
function loginText(acc: Account) {
  const host = window.location.hostname;
  const url = host === '127.0.0.1' || host === 'localhost' ? 'https://irontrader.asia' : window.location.origin;
  return `IronTrader 登录信息\n地址：${url}\n用户名：${acc.username}\n密码：${acc.password}\n（登录后可在右上角「修改密码」改成自己的密码）`;
}

export default function Accounts() {
  const isOwner = useIsOwner();
  const me = useMe().data;
  const qc = useQueryClient();
  const { message } = App.useApp();
  const [creating, setCreating] = useState(false);
  const [issued, setIssued] = useState<Account | null>(null);
  const [form] = Form.useForm();

  const users = useQuery({
    queryKey: ['admin-users'],
    queryFn: () => get<Account[]>('/api/admin/users'),
    enabled: isOwner,
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ['admin-users'] });

  const create = useMutation({
    mutationFn: (v: Partial<Account> & { password?: string }) => post<Account>('/api/admin/users', v),
    onSuccess: (acc) => {
      setCreating(false);
      form.resetFields();
      setIssued(acc);
      refresh();
    },
    onError: (e) => message.error((e as Error).message),
  });
  const update = useMutation({
    mutationFn: ({ username, ...body }: { username: string } & Record<string, unknown>) =>
      send<Account>('patch', `/api/admin/users/${encodeURIComponent(username)}`, body),
    onSuccess: (acc) => {
      if (acc.password) setIssued(acc);
      else message.success('已保存');
      refresh();
    },
    onError: (e) => message.error((e as Error).message),
  });
  const remove = useMutation({
    mutationFn: (username: string) => send<null>('delete', `/api/admin/users/${encodeURIComponent(username)}`),
    onSuccess: () => {
      message.success('已删除');
      refresh();
    },
    onError: (e) => message.error((e as Error).message),
  });

  if (!isOwner) {
    return (
      <div className="page">
        <Alert type="info" showIcon message="只有管理员可以管理账号" />
      </div>
    );
  }

  const list = users.data ?? [];
  const noOwnerAccount = users.isSuccess && !list.some((u) => u.role === 'owner' && !u.disabled);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>账号管理</h2>
          <p className="muted">
            给朋友开账号、重置密码、停用。停用或重置密码后，对方所有已登录的设备会立即退出。在你自己电脑上直接打开
            127.0.0.1:5002 不需要登录。
          </p>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
          新建账号
        </Button>
      </div>

      {noOwnerAccount && (
        <Alert
          type="warning"
          showIcon
          message="还没有管理员账号"
          description="你在外面（手机、公司）通过公网访问时也需要登录，建议先给自己建一个「管理员」账号。"
        />
      )}

      <Card>
        <Table<Account>
          size="middle"
          rowKey="username"
          loading={users.isLoading}
          dataSource={list}
          pagination={false}
          locale={{ emptyText: '还没有账号' }}
          columns={[
            {
              title: '用户名',
              dataIndex: 'username',
              render: (v: string, r) => (
                <span>
                  <b>{v}</b>
                  {r.display_name && r.display_name !== v && <span className="muted"> · {r.display_name}</span>}
                  {me?.username === v && <Tag bordered={false} style={{ marginLeft: 8 }}>我</Tag>}
                </span>
              ),
            },
            {
              title: '角色',
              dataIndex: 'role',
              width: 130,
              render: (role: Account['role'], r) => (
                <Select
                  size="small"
                  value={role}
                  style={{ width: 100 }}
                  options={[
                    { value: 'member', label: '成员' },
                    { value: 'owner', label: '管理员' },
                  ]}
                  onChange={(v) => update.mutate({ username: r.username, role: v })}
                />
              ),
            },
            {
              title: '状态',
              dataIndex: 'disabled',
              width: 90,
              render: (d: boolean) => (d ? <Tag color="default">已停用</Tag> : <Tag color="success">正常</Tag>),
            },
            { title: '备注', dataIndex: 'note', render: (v?: string) => <span className="muted">{v || ''}</span> },
            {
              title: '',
              key: 'actions',
              align: 'right',
              render: (_, r) => (
                <Space size={4} wrap>
                  <Popconfirm
                    title={`重置 ${r.username} 的密码？`}
                    description="会生成新密码，对方已登录的设备会退出"
                    okText="重置"
                    cancelText="取消"
                    onConfirm={() => update.mutate({ username: r.username, reset_password: true })}
                  >
                    <Button size="small">重置密码</Button>
                  </Popconfirm>
                  <Button
                    size="small"
                    onClick={() => update.mutate({ username: r.username, disabled: !r.disabled })}
                  >
                    {r.disabled ? '启用' : '停用'}
                  </Button>
                  <Popconfirm
                    title={`删除账号 ${r.username}？`}
                    okText="删除"
                    okButtonProps={{ danger: true }}
                    cancelText="取消"
                    onConfirm={() => remove.mutate(r.username)}
                  >
                    <Button size="small" danger type="text">
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <p className="muted small">
        成员可以看全部页面、做个股研究和选股扫描（扫描每小时 4 次、每天 12 次）；回测、重建作战台候选、账号管理只有管理员可以用。
      </p>

      <Modal
        open={creating}
        title="新建账号"
        okText="创建"
        cancelText="取消"
        confirmLoading={create.isPending}
        onCancel={() => setCreating(false)}
        onOk={async () => create.mutate(await form.validateFields())}
      >
        <Form form={form} layout="vertical" requiredMark={false} initialValues={{ role: 'member' }}>
          <Form.Item
            name="username"
            label="用户名（登录用）"
            rules={[
              { required: true, message: '请输入用户名' },
              { pattern: /^[A-Za-z0-9_.\-一-龥]{2,20}$/, message: '2–20 位中英文、数字、下划线、点或横线' },
            ]}
          >
            <Input placeholder="如 aqiang 或 阿强" autoComplete="off" />
          </Form.Item>
          <Form.Item name="display_name" label="显示名称（可选）">
            <Input placeholder="页面右上角显示的名字" />
          </Form.Item>
          <Form.Item name="role" label="角色">
            <Select
              options={[
                { value: 'member', label: '成员（看、研究、扫描，有次数限制）' },
                { value: 'owner', label: '管理员（全部权限，包括账号管理）' },
              ]}
            />
          </Form.Item>
          <Form.Item name="password" label="密码（可选）" rules={[{ min: 8, message: '至少 8 位' }]} extra="留空则自动生成一个好记的密码">
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="note" label="备注（可选）">
            <Input placeholder="如：大学同学" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={!!issued}
        title="账号已就绪，请把下面的登录信息发给对方"
        okText="复制并关闭"
        cancelText="关闭"
        onCancel={() => setIssued(null)}
        onOk={async () => {
          if (issued) {
            try {
              await navigator.clipboard.writeText(loginText(issued));
              message.success('已复制');
            } catch {
              message.info('浏览器不允许自动复制，请手动选中复制');
            }
          }
          setIssued(null);
        }}
      >
        {issued && (
          <>
            <Typography.Paragraph>
              <pre className="login-slip">{loginText(issued)}</pre>
            </Typography.Paragraph>
            <Alert type="warning" showIcon message="密码只显示这一次；忘了可以再点「重置密码」生成新的。" />
          </>
        )}
      </Modal>
    </div>
  );
}
