# 证书代发

全部必考科目官方确认通过后，课程报名具备证书资格。`CertificateCase` 对课程报名幂等创建，状态依次为 `ELIGIBLE`、`APPLYING`、`ISSUED`、`RECEIVED_BY_SCHOOL`、`READY_FOR_DELIVERY` 和 `DELIVERED`。

学校收到证书只表示实物进入学校保管，学员领取或快递签收后才进入 `DELIVERED`。证书编号和快递单号加密保存，普通接口只返回尾号掩码。每次迁移写入 `CertificateDeliveryEvent`，包括经办人、时间、前后状态和备注。

证书扫描件和签收凭证通过 Sprint 2 的 `FileObject` 关联。官方成绩修订导致资格失效时，系统把案例标记为 `EXCEPTION` 并记录严重异常，不撤销或删除既有证书历史。
