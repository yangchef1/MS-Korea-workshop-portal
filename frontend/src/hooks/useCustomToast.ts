import { toast } from "sonner"

const useCustomToast = () => {
  const showSuccessToast = (message: string) => {
    toast.success(message)
  }

  const showErrorToast = (message: string) => {
    toast.error(message)
  }

  const showInfoToast = (message: string) => {
    toast.info(message)
  }

  const showWarningToast = (message: string) => {
    toast.warning(message)
  }

  return {
    showSuccessToast,
    showErrorToast,
    showInfoToast,
    showWarningToast,
  }
}

export default useCustomToast
